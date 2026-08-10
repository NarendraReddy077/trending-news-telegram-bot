#!/usr/bin/env python3
import os

import aws_cdk as cdk

from telegram_news_bot.telegram_news_bot_stack import TelegramNewsBotStack


app = cdk.App()
TelegramNewsBotStack(app, "TelegramNewsBotStack", )

app.synth()
