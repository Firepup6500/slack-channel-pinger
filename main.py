from os import environ as env
from slack_bolt.async_app import AsyncApp
from dotenv import load_dotenv
from quart import Quart, request
from threading import Thread
from asyncio import run as aRun
from async_timeout import timeout
from aiohttp import ClientSession
from urllib.parse import unquote
from fpsql import sql

quartApp = Quart(__name__)
load_dotenv()

for requiredVar in ["SLACK_BOT_TOKEN", "CLIENT_ID", "CLIENT_SECRET", "OWNER_ID"]:
    if not env.get(requiredVar):
        raise ValueError(
            f'Missing required environment variable "{requiredVar}". Please create a .env file in the same directory as this script and define the missing variable.'
        )

app = AsyncApp(token=env["SLACK_BOT_TOKEN"])


async def pingChannel(data):
    if data["channel_name"] == "directmessage" or (
        data["channel_name"].startswith("mpdm-") and "--" in data["channel_name"]
    ):
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(data["response_url"]),
                json={"text": "I don't work in DMs, sorry!"},
            )
        return
    if env["OWNER_ID"] == data["user_id"]:
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(data["response_url"]),
                json={
                    "text": f"<!channel> pinged by <@{data['user_id']}>",
                    "response_type": "in_channel",
                },
            )
        return
    try:
        info = await app.client.conversations_info(data["channel_id"])
        if info["creator"] != data["user_id"]:
            async with ClientSession(
                headers={"Content-type": "application/json"}
            ) as session:
                await session.post(
                    unquote(data["response_url"]),
                    json={"text": "You need to have created the channel to use me!"},
                )
            return
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": f"<!channel> pinged by <@{data['user_id']}>",
                "response_type": "in_channel",
            },
        )
    except Exception:
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(data["response_url"]),
                json={
                    "text": "Sorry buddy, but I can't ping private channels without checking who owns the channel first! You'll need to add me to this channel before I can work here."
                },
            )


@quartApp.route(
    "/command/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)
async def invalid():
    return '{"ok":false,"error":"method_not_allowed","http_code":405}', 405


@quartApp.route("/command/", methods=["POST"])
async def command():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]
    # print("Data:", data)

    Thread(target=aRun, args=(pingChannel(data),), daemon=True).start()

    return "", 200


if __name__ == "__main__":
    quartApp.run(host="0.0.0.0", port=65099)
    print()
