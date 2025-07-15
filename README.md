# HTML to Markdown Converter

A Python CLI tool that converts HTML files to Markdown using Google's Gemini API. This tool is designed to process entire directories of HTML files (downloaded web pages) and convert them to clean, structured Markdown format.

## Features

- **Batch Processing**: Convert multiple HTML files in a directory at once
- **Chronological Ordering**: Files are processed and concatenated in chronological order based on modification time
- **Parallel Processing**: Async processing with configurable concurrency for fast conversion
- **Smart HTML Cleaning**: Removes scripts, styles, and navigation elements while preserving content structure
- **Rate Limiting**: Built-in rate limiting to respect API limits
- **Error Handling**: Robust retry logic with exponential backoff
- **Progress Tracking**: Real-time progress updates during processing
- **Configurable**: JSON-based configuration with CLI overrides
- **Logging**: Comprehensive logging with file rotation

## Installation

1. Clone or download this repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## API Key Setup

You need a Google Gemini API key to use this tool. Get one from [Google AI Studio](https://aistudio.google.com/).

Set up your API key in one of these ways:

### Option 1: Environment Variable
```bash
export GEMINI_API_KEY="your-api-key-here"
```

### Option 2: Command Line Argument
```bash
python html2md.py /path/to/html/files --api-key "your-api-key-here"
```

## Usage

### Basic Usage
```bash
python html2md.py /path/to/html/files
```

### Advanced Usage
```bash
python html2md.py /path/to/html/files \
    --api-key "your-api-key" \
    --output "converted.md" \
    --concurrent 5 \
    --log-level DEBUG
```

### Command Line Options

- `directory`: Directory containing HTML files to convert (required)
- `--api-key`: Gemini API key (optional if GEMINI_API_KEY env var is set)
- `--config`: Configuration file path (default: config.json)
- `--concurrent`: Number of concurrent requests (overrides config)
- `--log-level`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `--output`: Output filename (default: output.md)

### Examples

Convert HTML files in current directory:
```bash
python html2md.py .
```

Convert with custom output filename:
```bash
python html2md.py /path/to/html/files --output my-converted-content.md
```

Convert with debugging enabled:
```bash
python html2md.py /path/to/html/files --log-level DEBUG
```

## Configuration

The tool uses a `config.json` file for configuration.

### Configuration Options

- **gemini.model**: Gemini model to use
- **gemini.thinking_budget**: Thinking budget for the model (-1 for auto)
- **gemini.max_retries**: Maximum retry attempts for failed requests
- **processing.max_concurrent**: Maximum concurrent API requests
- **processing.rate_limit_per_minute**: Rate limit for API requests
- **html_cleaning.remove_tags**: HTML tags to remove during cleaning
- **output.separator**: Separator between converted files

## Output Format

The tool generates a single Markdown file with this structure:

```markdown
# First Page Title

[Converted markdown content from first HTML file]

---

# Second Page Title

[Converted markdown content from second HTML file]

---

# Third Page Title

[Converted markdown content from third HTML file]
```

## Error Handling

- **API Failures**: Automatic retry with exponential backoff
- **Rate Limits**: Built-in rate limiting with backoff
- **File Errors**: Logs errors and continues processing other files
- **Network Issues**: Robust retry logic for network failures

## Logging

Logs are written to `logs/html2md.log` with automatic rotation. Log levels:

- **DEBUG**: Detailed processing information
- **INFO**: General processing status
- **WARNING**: Non-critical issues
- **ERROR**: Serious errors that prevent processing

## Troubleshooting

### Common Issues

1. **API Key Error**: Ensure your API key is valid and has sufficient quota
2. **Rate Limiting**: Reduce concurrent requests in config if hitting limits
3. **File Not Found**: Ensure HTML files exist in the specified directory
4. **Memory Issues**: Reduce concurrent processing for large files

### Debug Mode

Run with debug logging to see detailed processing information:
```bash
python html2md.py /path/to/html/files --log-level DEBUG
```

## Requirements

- Python 3.7+
- Internet connection for API calls
- Valid Google Gemini API key

## Dependencies

- `google-genai`: Google Gemini API client
- `beautifulsoup4`: HTML parsing and cleaning
- `aiolimiter`: Rate limiting for async requests
