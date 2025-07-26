#!/usr/bin/env python3
"""
HTML to Markdown Converter
A CLI tool that converts HTML files to markdown using Google's Gemini API.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import time
import html
import re
from logging.handlers import RotatingFileHandler

import aiolimiter
from bs4 import BeautifulSoup, Comment
from google import genai
from google.genai import types


class Config:
    """Configuration management class."""
    
    def __init__(self, config_path: str = "config.json"):
        self.config_path = config_path
        self.config = self._load_config()
    
    def _load_config(self) -> Dict:
        """Load configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            logging.error(f"Configuration file {self.config_path} not found")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON in {self.config_path}: {e}")
            sys.exit(1)
    
    def get(self, key: str, default=None):
        """Get configuration value using dot notation."""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value


class HTMLProcessor:
    """HTML processing and cleaning utilities."""
    
    def __init__(self, config: Config):
        self.config = config
        self.remove_tags = config.get('html_cleaning.remove_tags', [])
    
    def clean_html(self, html_content: str) -> str:
        """Clean HTML content by removing unwanted elements."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove specified tags
        for tag_name in self.remove_tags:
            for element in soup.find_all(tag_name):
                element.decompose()
        
        # Remove HTML comments
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove inline styles
        for tag in soup.find_all(True):
            if 'style' in tag.attrs:
                del tag['style']
        
        # Return cleaned HTML
        return str(soup)
    
    def clean_filename(self, filename: str) -> str:
        """Clean filename for use as markdown header."""
        # Remove extension
        name = Path(filename).stem
        
        # Replace underscores with spaces
        name = name.replace('_', ' ')
        
        # Decode HTML entities
        name = html.unescape(name)
        
        # Remove or replace special characters
        name = re.sub(r'[<>:"/\\|?*]', '', name)
        
        # Clean up extra spaces
        name = re.sub(r'\s+', ' ', name).strip()
        
        return name


class GeminiAPIClient:
    """Gemini API client for HTML to Markdown conversion."""
    
    def __init__(self, api_key: str, config: Config):
        self.api_key = api_key
        self.config = config
        self.client = genai.Client(api_key=api_key)
        self.model = config.get('gemini.model')
        self.thinking_budget = config.get('gemini.thinking_budget', -1)
        self.max_retries = config.get('gemini.max_retries', 3)
        self.retry_delay_base = config.get('gemini.retry_delay_base', 1.0)
        
        # Rate limiting
        rate_limit = config.get('processing.rate_limit_per_minute', 875)
        self.rate_limiter = aiolimiter.AsyncLimiter(rate_limit, 60)
        
        self.logger = logging.getLogger(__name__)
    
    async def convert_html_to_markdown(self, html_content: str, filename: str) -> str:
        """Convert HTML content to markdown using Gemini API."""
        prompt = f"""Convert this HTML content to clean markdown format. 

Guidelines:
- Focus on the main content, ignore navigation and UI elements
- Start directly with the main content - skip metadata
- Use hashtags for headings (e.g. "## Description", "## Solution", "## Tests", "## Library", etc.), do NOT use a single hashtag
- Preserve the structure and formatting of the content
- Convert HTML elements to appropriate markdown equivalents
- Do NOT use horizontal rules (---) in your output
- Keep code blocks, tables, and other structured content intact
- Remove any advertisements, navigation, or non-content elements

HTML Content:
{html_content}"""
        
        async with self.rate_limiter:
            for attempt in range(self.max_retries):
                try:
                    response = await self._make_api_call(prompt)
                    self.logger.info(f"Successfully converted {filename}")
                    return response
                except Exception as e:
                    self.logger.warning(f"Attempt {attempt + 1} failed for {filename}: {e}")
                    if attempt < self.max_retries - 1:
                        delay = self.retry_delay_base * (2 ** attempt)
                        await asyncio.sleep(delay)
                    else:
                        self.logger.error(f"Failed to convert {filename} after {self.max_retries} attempts")
                        raise
    
    async def _make_api_call(self, prompt: str) -> str:
        """Make API call to Gemini."""
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(
                        thinking_budget=self.thinking_budget,
                        include_thoughts=False
                    )
                )
            )
            return response.text
        except Exception as e:
            error_str = str(e)
            self.logger.error(f"API call failed: {error_str}")
            
            # Check for 429 rate limit error and extract retry delay
            if "429" in error_str and "RESOURCE_EXHAUSTED" in error_str:
                import re
                retry_match = re.search(r"'retryDelay': '(\d+)s'", error_str)
                if retry_match:
                    retry_delay = int(retry_match.group(1))
                    self.logger.info(f"Rate limited, waiting {retry_delay} seconds")
                    await asyncio.sleep(retry_delay)
            
            raise


class HTML2MDConverter:
    """Main converter class that orchestrates the conversion process."""
    
    def __init__(self, config: Config, api_key: str):
        self.config = config
        self.html_processor = HTMLProcessor(config)
        self.api_client = GeminiAPIClient(api_key, config)
        self.logger = logging.getLogger(__name__)
        
        # Semaphore for concurrent processing
        max_concurrent = config.get('processing.max_concurrent', 20)
        self.semaphore = asyncio.Semaphore(max_concurrent)
    
    def discover_html_files(self, directory: str) -> List[Tuple[str, float]]:
        """Discover HTML files in directory and sort by modification time."""
        html_files = []
        directory_path = Path(directory)
        
        if not directory_path.exists():
            self.logger.error(f"Directory {directory} does not exist")
            return []
        
        for file_path in directory_path.glob("*.html"):
            if file_path.is_file():
                mtime = file_path.stat().st_mtime
                html_files.append((str(file_path), mtime))
        
        # Sort by modification time (chronological order)
        html_files.sort(key=lambda x: x[1])
        
        self.logger.info(f"Found {len(html_files)} HTML files in {directory}")
        return html_files
    
    def check_output_file(self, output_path: str) -> Optional[str]:
        """Check if output file exists and get user confirmation.
        
        Returns:
            str: The output path to use (may be modified with timestamp)
            None: If operation was cancelled
        """
        if os.path.exists(output_path):
            print(f"Output file '{output_path}' already exists.")
            print("Options:")
            print("1. Overwrite existing file")
            print("2. Append timestamp to create new file")
            print("3. Cancel operation")
            
            while True:
                choice = input("Enter your choice (1-3): ").strip()
                if choice == '1':
                    return output_path
                elif choice == '2':
                    timestamp = int(time.time())
                    base_dir = os.path.dirname(output_path)
                    new_name = f"{Path(output_path).stem}_{timestamp}.md"
                    return os.path.join(base_dir, new_name)
                elif choice == '3':
                    print("Operation cancelled.")
                    return None
                else:
                    print("Invalid choice. Please enter 1, 2, or 3.")
        
        return output_path
    
    async def process_file(self, file_path: str, total_files: int, current_index: int) -> Tuple[str, str]:
        """Process a single HTML file."""
        async with self.semaphore:
            filename = Path(file_path).name
            self.logger.info(f"Processing {filename} ({current_index + 1}/{total_files})")
            
            try:
                # Read HTML file
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    html_content = f.read()
                
                # Clean HTML
                cleaned_html = self.html_processor.clean_html(html_content)
                
                # Convert to markdown
                markdown_content = await self.api_client.convert_html_to_markdown(
                    cleaned_html, filename
                )
                
                # Clean filename for header
                clean_filename = self.html_processor.clean_filename(filename)
                
                return clean_filename, markdown_content
                
            except Exception as e:
                self.logger.error(f"Error processing {filename}: {e}")
                raise
    
    async def convert_directory(self, directory: str, output_file: str) -> None:
        """Convert all HTML files in directory to markdown."""
        # Discover HTML files
        html_files = self.discover_html_files(directory)
        
        if not html_files:
            print("No HTML files found in the directory.")
            return
        
        # Check output file
        output_path = os.path.join(directory, output_file)
        output_path = self.check_output_file(output_path)
        if output_path is None:
            return
        
        print(f"Processing {len(html_files)} HTML files...")
        
        # Create tasks for all files
        tasks = []
        for i, (file_path, _) in enumerate(html_files):
            task = self.process_file(file_path, len(html_files), i)
            tasks.append(task)
        
        # Process files concurrently
        processed_files = []
        completed = 0
        
        for coro in asyncio.as_completed(tasks):
            try:
                result = await coro
                processed_files.append(result)
                completed += 1
                
                # Update progress
                current_file = result[0]  # Use filename from task result
                print(f"Completed {current_file} ({completed}/{len(html_files)})")
                
            except Exception as e:
                self.logger.error(f"Failed to process file: {e}")
                # Continue with other files
        
        # Sort results to maintain chronological order
        # Map results back to original order
        file_to_result = {result[0]: result for result in processed_files}
        ordered_results = []
        
        for file_path, _ in html_files:
            filename = Path(file_path).name
            clean_filename = self.html_processor.clean_filename(filename)
            if clean_filename in file_to_result:
                ordered_results.append(file_to_result[clean_filename])
        
        # Generate output
        self.generate_output(ordered_results, output_path)
        
        print(f"Conversion completed! Output saved to: {output_path}")
        print(f"Successfully processed {len(ordered_results)} out of {len(html_files)} files.")
    
    def generate_output(self, results: List[Tuple[str, str]], output_path: str) -> None:
        """Generate final markdown output."""
        separator = self.config.get('output.separator', '---')
        add_headers = self.config.get('output.add_headers', True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            for i, (filename, content) in enumerate(results):
                # Add header if add_headers is True
                if add_headers:
                    f.write(f"# {filename}\n\n")
                
                # Add content
                f.write(content.strip())
                f.write('\n\n')
                
                # Add separator (except for last file)
                if i < len(results) - 1:
                    f.write(f"{separator}\n\n")


def setup_logging(config: Config, log_level: str = None) -> None:
    """Setup logging configuration."""
    level = log_level or config.get('logging.level', 'INFO')
    log_file = config.get('logging.file', 'logs/html2md.log')
    max_bytes = config.get('logging.max_bytes', 10485760)  # 10MB
    backup_count = config.get('logging.backup_count', 5)
    
    # Ensure log directory exists
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    
    # Create logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))
    
    # File handler with rotation
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count
    )
    file_handler.setLevel(getattr(logging, level.upper()))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Convert HTML files to Markdown using Google Gemini API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python html2md.py /path/to/html/files
  python html2md.py /path/to/html/files --api-key YOUR_API_KEY
  python html2md.py /path/to/html/files --output combined.md
  python html2md.py /path/to/html/files --concurrent 20 --log-level DEBUG
        """
    )
    
    parser.add_argument(
        'directory',
        help='Directory containing HTML files to convert'
    )
    
    parser.add_argument(
        '--api-key',
        help='Gemini API key (can also use GEMINI_API_KEY env var)'
    )
    
    parser.add_argument(
        '--config',
        default='config.json',
        help='Configuration file path (default: config.json)'
    )
    
    parser.add_argument(
        '--concurrent',
        type=int,
        help='Number of concurrent requests (overrides config)'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (overrides config)'
    )
    
    parser.add_argument(
        '--output',
        default='output.md',
        help='Output filename (default: output.md)'
    )
    
    args = parser.parse_args()
    
    # Load configuration
    config = Config(args.config)
    
    # Setup logging
    setup_logging(config, args.log_level)
    
    # Get API key
    api_key = args.api_key or os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("Error: API key required. Use --api-key or set GEMINI_API_KEY environment variable.")
        sys.exit(1)
    
    # Override config with CLI args
    if args.concurrent:
        config.config['processing']['max_concurrent'] = args.concurrent
    
    # Create converter and run
    converter = HTML2MDConverter(config, api_key)
    
    try:
        asyncio.run(converter.convert_directory(args.directory, args.output))
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Conversion failed: {e}")
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
