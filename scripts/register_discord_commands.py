#!/usr/bin/env python3
"""
Register Discord slash commands for Second Brain bot.

Usage:
    # Register to the default guild (instant)
    python register_discord_commands.py

    # Register globally (takes up to 1 hour to propagate)
    python register_discord_commands.py --global

    # Use a different AWS profile
    python register_discord_commands.py --profile my-profile

    # Dry run (show commands without registering)
    python register_discord_commands.py --dry-run
"""

import argparse
import json
import sys

import boto3
import requests


# Discord API base URL
DISCORD_API_BASE = "https://discord.com/api/v10"

# Default guild/server ID
DEFAULT_GUILD_ID = "1438958317513740421"

# Slash commands to register
# Type 3 = STRING option
COMMANDS = [
    {
        "name": "remember",
        "description": "Save a fact or piece of information to your knowledge base",
        "options": [
            {
                "name": "fact",
                "description": "The information to remember (e.g., 'John's birthday is March 15')",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "save",
        "description": "Save information to your knowledge base (alias for /remember)",
        "options": [
            {
                "name": "fact",
                "description": "The information to save",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "ask",
        "description": "Ask a question about your stored knowledge",
        "options": [
            {
                "name": "question",
                "description": "Your question (e.g., 'When is John's birthday?')",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "query",
        "description": "Query your knowledge base (alias for /ask)",
        "options": [
            {
                "name": "question",
                "description": "Your query",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "briefing",
        "description": "Get your personalized morning briefing with calendar, reminders, and updates",
    },
    {
        "name": "edit",
        "description": "Edit or correct a fact in your knowledge base",
        "options": [
            {
                "name": "message",
                "description": "Describe what to change (e.g., 'Change John's birthday from March 15 to March 16')",
                "type": 3,
                "required": True,
            }
        ],
    },
    {
        "name": "forget",
        "description": "Remove a fact from your knowledge base",
        "options": [
            {
                "name": "message",
                "description": "Describe what to forget (e.g., 'Forget John's birthday')",
                "type": 3,
                "required": True,
            }
        ],
    },
]


def get_discord_credentials(profile: str | None = None) -> dict:
    """Fetch Discord credentials from AWS Secrets Manager."""
    session = boto3.Session(profile_name=profile) if profile else boto3.Session()
    client = session.client("secretsmanager")

    try:
        response = client.get_secret_value(SecretId="second-brain/discord")
        return json.loads(response["SecretString"])
    except client.exceptions.ResourceNotFoundException:
        print("Error: Secret 'second-brain/discord' not found in Secrets Manager")
        sys.exit(1)
    except Exception as e:
        print(f"Error fetching credentials: {e}")
        sys.exit(1)


def register_commands(
    application_id: str,
    bot_token: str,
    guild_id: str | None = None,
    dry_run: bool = False,
) -> None:
    """Register slash commands with Discord API."""

    # Build URL - guild-specific or global
    if guild_id:
        url = f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands"
        scope = f"guild {guild_id}"
    else:
        url = f"{DISCORD_API_BASE}/applications/{application_id}/commands"
        scope = "global"

    headers = {
        "Authorization": f"Bot {bot_token}",
        "Content-Type": "application/json",
    }

    print(f"Registering {len(COMMANDS)} commands ({scope})...")
    print()

    if dry_run:
        print("DRY RUN - Commands that would be registered:")
        print(json.dumps(COMMANDS, indent=2))
        return

    # PUT replaces all commands (idempotent)
    response = requests.put(url, headers=headers, json=COMMANDS)

    if response.status_code == 200:
        registered = response.json()
        print(f"Successfully registered {len(registered)} commands:")
        for cmd in registered:
            options_str = ""
            if cmd.get("options"):
                opts = [f"<{o['name']}>" for o in cmd["options"]]
                options_str = " " + " ".join(opts)
            print(f"  /{cmd['name']}{options_str} - {cmd['description']}")

        if not guild_id:
            print()
            print("Note: Global commands may take up to 1 hour to appear in Discord.")
    elif response.status_code == 401:
        print("Error: Invalid bot token. Check your credentials in Secrets Manager.")
        sys.exit(1)
    elif response.status_code == 403:
        print("Error: Bot lacks permission. Ensure the bot has 'applications.commands' scope.")
        sys.exit(1)
    else:
        print(f"Error registering commands: {response.status_code}")
        print(response.text)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Register Discord slash commands for Second Brain bot"
    )
    parser.add_argument(
        "--global",
        dest="global_",
        action="store_true",
        help="Register globally (slow, up to 1 hour). Default is guild-only (instant).",
    )
    parser.add_argument(
        "--profile",
        help="AWS profile to use for Secrets Manager",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show commands without registering",
    )
    args = parser.parse_args()

    # Get credentials from Secrets Manager
    print("Fetching Discord credentials from AWS Secrets Manager...")
    credentials = get_discord_credentials(args.profile)

    application_id = credentials.get("application_id")
    bot_token = credentials.get("bot_token")

    if not application_id or not bot_token:
        print("Error: Missing 'application_id' or 'bot_token' in secret")
        sys.exit(1)

    print(f"Application ID: {application_id}")
    print()

    # Register commands (guild-specific by default, global if --global flag)
    guild_id = None if args.global_ else DEFAULT_GUILD_ID
    register_commands(
        application_id=application_id,
        bot_token=bot_token,
        guild_id=guild_id,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
