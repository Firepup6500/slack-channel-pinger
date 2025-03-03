import os, sys
from slack_bolt import App
from dotenv import load_dotenv
from traceback import format_exc
from flask import Flask
from requests import get, post

load_dotenv()

for requiredVar in ["SLACK_BOT_TOKEN", "SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"]:
    if not os.environ.get(requiredVar):
        raise ValueError(
            f'Missing required environment variable "{requiredVar}". Please create a .env file in the same directory as this script and define the missing variable.'
        )
