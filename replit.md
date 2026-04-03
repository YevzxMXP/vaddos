# Momo Discord Bot

## Overview

This is a Discord bot named "Momo" that uses a Markov Chain algorithm to learn from messages and generate text responses. The bot monitors a specific Discord channel, learns from the messages posted there, and can generate sentences based on the patterns it has learned.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Core Components

**Discord Bot Framework**
- Uses discord.py library with the commands extension for bot functionality
- Configured with specific intents: message_content, messages, and guilds
- Uses "!" as the command prefix
- Targets a specific channel (hardcoded channel ID) for learning

**Markov Chain Text Generation**
- Custom implementation of a 2-word Markov Chain for text generation
- Stores word pair sequences in a dictionary-based chain
- Generates sentences by randomly walking through learned word patterns
- Maximum sentence length capped at 20 words by default

**Configuration**
- Discord bot token loaded from environment variable (DISCORD_TOKEN)
- Target channel ID hardcoded in the application

### Design Decisions

**Simple Markov Chain over Complex NLP**
- Chose a basic 2-gram Markov Chain for simplicity and low resource usage
- Trade-off: Less coherent output compared to neural language models, but lightweight and easy to understand

**In-Memory Storage**
- Chain data stored in Python dictionaries (in-memory)
- Trade-off: Data is lost on restart, but avoids database complexity for a simple bot

**Flask Dependency**
- Flask is included in requirements, likely for a keep-alive web server to prevent the bot from sleeping on hosting platforms

## External Dependencies

### Python Packages
- **discord.py (>=2.4.0)**: Core Discord API wrapper for bot functionality
- **aiofiles (>=23.2.1)**: Async file operations (available but not currently used in main.py)
- **python-dotenv (>=1.0.0)**: Environment variable loading from .env files
- **Flask (>=3.0.0)**: Web framework, likely for keep-alive endpoint

### External Services
- **Discord API**: Primary integration for bot messaging and channel monitoring
- Requires DISCORD_TOKEN environment variable for authentication

### Runtime
- Python 3.10.12