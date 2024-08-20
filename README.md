# Ollama-like API for Venice

- [Introduction](#introduction)
- [Installation](#installation)
- [Usage](#usage)
- [Setting up Open-WebUI](#setting-up-open-webui)
- [Setting up continue.dev](#setting-up-continuedev)
- [Contributing](#contributing)

## Introduction

This project simulates the Ollama API using Venice.ai's text generation capabilities, allowing users to access a lifetime Pro account without token fees, usage costs, or subscriptions. The project uses Selenium automation framework to interact with Venice in a clever way, making it suitable for personal inference and integration with IDEs and LLM front-ends.

## Installation

To install the project, follow these steps:

Make sure pip and python commands are Python 3.11 or higher. If you are not sure, run this command:

```bash
pip --version
python --version
```

Especially note if pip and python are different python versions, that might cause problems.

If they are lower version, you might try calling a command with version (python3.11, pip3.11 or python3 and pip3)

Navigate to the project directory using `cd ollama-like-api-for-venice`

Start by first creating and activating a Python virtual environment (optional but recommended):

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the required dependencies

```bash
pip install -r requirements.txt
```

## Usage

First make sure that the virtual environment is activated by running `source .venv/bin/activate` in the project's directory.

Then set the environment variables, run the following commands in your terminal:

```bash
export VENICE_USERNAME="your-username"
export VENICE_PASSWORD="your-password"
```

Replace "your-username" and "your-password" with your actual Venice credentials.

Run the server using `python ollama_like_server.py`

If you need to set additional options, see the options:

```
# python ollama_like_server.py --help
usage: ollama_like_server.py [-h] [--username USERNAME] [--password PASSWORD]
                             [--host HOST] [--port PORT] [--timeout TIMEOUT]
                             [--selenium-timeout SELENIUM_TIMEOUT]
                             [--headless] [--no-headless] [--debug-browser]

Ollama-like API for venice.ai

options:
  -h, --help            show this help message and exit
  --username USERNAME   Venice username
  --password PASSWORD   Venice password
  --host HOST           Local host address
  --port PORT           Server port
  --timeout TIMEOUT     Timeout for generating tokens from Venice (seconds)
  --selenium-timeout SELENIUM_TIMEOUT
                        Selenium timeout (seconds)
  --headless            Run Selenium in headless mode
  --no-headless         Disable headless mode and run with a visible browser
                        window
  --debug-browser       Enable browser debugging logs
```

## Troubleshooting

If you get WebDriver errors, first make sure that you can run the Chrome binary from the command line.

Replace `/path/to/your/google-chrome` with your path to Chrome.

```bash
/path/to/your/google-chrome e --headless --disable-gpu --dump-dom https://bitcoin.org/ | head -n 20 | grep "Bitcoin"
```

The output should be something like:
```html
<title>Bitcoin - Open source P2P money</title>
<meta name="description" content="Bitcoin is an innovative payment network and a new kind of money. Find all you need to know and get started with Bitcoin on bitcoin.org.">
```

If it does not work, use your operating system's package manager to install Chrome and all the required libraries.

## Setting up Open-WebUI

Now you can use the provided API with [Open-WebUI](https://openwebui.com/). Install it [according to the instructions](https://docs.openwebui.com/getting-started/).

After login to the Open-WebUI interface, click on your account (top right icon), then click on Admin Panel, choose the Settings tab, go to Connections.
Under the Ollama API either change the URL (if you don't run local Ollama), or
click "+" to add new entry and type in http://127.0.0.1:9999 (adjust the port
to match your local server configuration, 9999 is just default).

Then click on the arrows icon, which will verify the connection. If everything is ok, you should see the new models under new chat - the models are
"llama-3.1-405b-akash-api", "hermes-2-theta-web", "dogge-llama-3-70b". 

Hermes-2-theta has access to web search, llama-3.1-405b is the currently best open model.

## Setting up continue.dev

To use [continue.dev](https://continue.dev/) to help with your web development 
needs (or writing README-s like this one😅), install the extension into your Visual Studio Code or JetBrains-based IDE (I haven't tested JetBrains).

Then press the Continue button in the status bar and click on "Configure autocomplete options". An editor will appear. Add the models to models array,
for example this is a complete configuration:

```json
{
  "models": [
    {
      "title": "venice llama3.1-405b",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "llama-3.1-405b-akash-api"
    },
    {
      "title": "venice dogge-llama-3-70b",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "dogge-llama-3-70b"
    },
    {
      "title": "venice hermes-2-theta-web",
      "provider": "ollama",
      "apiBase": "http://localhost:9999",
      "model": "hermes-2-theta-web"
    }
  ],
  "tabAutocompleteModel": {
    "title": "Starcoder",
    "provider": "ollama",
    "model": "starcoder2:3b"
  },
  "embeddingsProvider": {
    "provider": "ollama",
    "model": "nomic-embed-text"
  },
  "allowAnonymousTelemetry": false,
  "docs": []
}
```

I recommend installing also ollama and running the starcoder2 model locally.
For search you will need the embeddings provider and that should also run 
locally. The embeddings model is used for indexing your codebase and then providing relevant snippets to the model and it needs to run locally through local ollama (not this project, Venice does not provide embeddings API).

Embeddings are very lightweight, so they can run locally on almost any hardware.

## Contributing

This project is currently crowdfunded, and the code will be released as a FOSS project on GitHub once the funding goal is reached. If you're interested in contributing to the project now, send patches to me, if you are OK with the code being released possibly later, under a permissive license.

I would appreciate if you have directed your friends to the [crowdfunding page](https://pay.cypherpunk.today/apps/26zEBNn6FGAkzvVVuDMz3SXrKJLU/crowdfund
)
