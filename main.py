from os import environ as env
from slack_bolt.async_app import AsyncApp
from dotenv import load_dotenv
from quart import Quart, request
from threading import Thread
from asyncio import run as aRun
from async_timeout import timeout
from aiohttp import ClientSession
from urllib.parse import unquote
from fpsql import asyncSql
from traceback import format_exc
from slack_sdk.errors import SlackApiError

db = asyncSql("database.db")
quartApp = Quart(__name__)
load_dotenv()

for requiredVar in ["SLACK_BOT_TOKEN", "OWNER_ID"]:
    if not env.get(requiredVar):
        raise ValueError(
            f'Missing required environment variable "{requiredVar}". Please create a .env file in the same directory as this script and define the missing variable.'
        )

app = AsyncApp(token=env["SLACK_BOT_TOKEN"])


async def check(
    user_id: str,
    chan_id: str,
    chan_name: str,
    url: str,
    text: str,
    skip_db: bool = False,
) -> bool:
    try:
        if chan_name == "directmessage" or (
            chan_name.startswith("mpdm-") and "--" in chan_name
        ):
            async with ClientSession(
                headers={"Content-type": "application/json"}
            ) as session:
                await session.post(
                    unquote(url),
                    json={"text": "I don't work in DMs, sorry!"},
                )
            return False
        if text.lower() != "false" and env["OWNER_ID"] == user_id:
            return True
        vals = await db.get(chan_id)
        if not skip_db and vals and vals["unlocked"]:
            return True
        try:
            info = {}
            patched = False
            if vals and vals.get("owner"):
                patched = True
                info["channel"] = {"creator": vals["owner"]}
            else:
                info = await app.client.conversations_info(channel=chan_id)
            if info["channel"]["creator"] != user_id:
                async with ClientSession(
                    headers={"Content-type": "application/json"}
                ) as session:
                    await session.post(
                        unquote(url),
                        json={
                            "text": f"You need to own the channel to use me! (<@{info['channel']['creator']}> {'created' if not patched else 'owns'} this channel)"
                        },
                    )
                return False
            return True
        except SlackApiError:
            async with ClientSession(
                headers={"Content-type": "application/json"}
            ) as session:
                await session.post(
                    unquote(url),
                    json={
                        "text": "Sorry buddy, but I can't ping private channels without checking who owns the channel first! You'll need to add me to this channel before I can work here."
                    },
                )
            return False
    except Exception:
        print(format_exc())
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(url),
                json={
                    "text": f"Woah, wtf?!?! Something weird broke here, send <@{env['OWNER_ID']}> the following info:\n```\n{format_exc()}```"
                },
            )


async def pingChannel(data):
    if not await check(
        data["user_id"],
        data["channel_id"],
        data["channel_name"],
        data["response_url"],
        data["text"],
    ):
        return
    async with ClientSession(headers={"Content-type": "application/json"}) as session:
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": f"<!channel> pinged by <@{data['user_id']}>",
                "response_type": "in_channel",
            },
        )


async def pingHere(data):
    if not await check(
        data["user_id"],
        data["channel_id"],
        data["channel_name"],
        data["response_url"],
        data["text"],
    ):
        return
    async with ClientSession(headers={"Content-type": "application/json"}) as session:
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": f"<!here> pinged by <@{data['user_id']}>",
                "response_type": "in_channel",
            },
        )


async def lockChannel(data):
    if not await check(
        data["user_id"],
        data["channel_id"],
        data["channel_name"],
        data["response_url"],
        data["text"],
        True,
    ):
        return
    vals = await db.get(data["channel_id"])
    if not vals or not vals["unlocked"]:
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(data["response_url"]),
                json={
                    "text": "This channel is already locked!",
                },
            )
        return
    if not vals:
        vals = {}
    vals["unlocked"] = False
    await db.set(data["channel_id"], vals)
    async with ClientSession(headers={"Content-type": "application/json"}) as session:
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": "This channel is now locked!",
            },
        )


async def unlockChannel(data):
    if not await check(
        data["user_id"],
        data["channel_id"],
        data["channel_name"],
        data["response_url"],
        data["text"],
    ):
        return
    vals = await db.get(data["channel_id"])
    if vals and vals["unlocked"]:
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            await session.post(
                unquote(data["response_url"]),
                json={
                    "text": "This channel is already unlocked!",
                },
            )
        return
    if not vals:
        vals = {}
    vals["unlocked"] = True
    await db.set(data["channel_id"], vals)
    async with ClientSession(headers={"Content-type": "application/json"}) as session:
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": "This channel is now unlocked!",
            },
        )


async def setOwner(data):
    if not await check(
        data["user_id"],
        data["channel_id"],
        data["channel_name"],
        data["response_url"],
        data["text"],
        True,
    ):
        return
    text = unquote(data["text"]).strip()
    if not (text.startswith("<@") and text.endswith(">") and "|" in text):
        async with ClientSession(
            headers={"Content-type": "application/json"}
        ) as session:
            print(text, flush=True)
            await session.post(
                unquote(data["response_url"]),
                json={
                    "text": "That's not a user ping... Please submit this command in the format of `/set-owner @someuser`",
                },
            )
        return
    vals = await db.get(data["channel_id"])
    if not vals:
        vals = {}
    vals["owner"] = text.split("@")[1].split("|")[0]
    await db.set(data["channel_id"], vals)
    async with ClientSession(headers={"Content-type": "application/json"}) as session:
        await session.post(
            unquote(data["response_url"]),
            json={
                "text": f"{text} now owns this channel!",
            },
        )


@quartApp.route(
    "/ping/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)
async def invalid():
    return '{"ok":false,"error":"method_not_allowed","http_code":405}', 405


quartApp.route(
    "/up/",
    methods=["POST", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/lock/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/unlock/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/here/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)
quartApp.route(
    "/set/",
    methods=["GET", "OPTIONS", "PUT", "HEAD", "DELETE", "CONNECT", "TRACE", "PATCH"],
)(invalid)


@quartApp.route("/up/", methods=["GET"])
async def up():
    return '{"ok":true,"http_code":200}'


@quartApp.route("/ping/", methods=["POST"])
async def ping():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]

    Thread(target=aRun, args=(pingChannel(data),), daemon=True).start()

    return ""


@quartApp.route("/here/", methods=["POST"])
async def here():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]

    Thread(target=aRun, args=(pingHere(data),), daemon=True).start()

    return ""


@quartApp.route("/set/", methods=["POST"])
async def set():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]

    Thread(target=aRun, args=(setOwner(data),), daemon=True).start()

    return ""


@quartApp.route("/unlock/", methods=["POST"])
async def unlock():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]

    Thread(target=aRun, args=(unlockChannel(data),), daemon=True).start()

    return "", 200


@quartApp.route("/lock/", methods=["POST"])
async def lock():
    rawData = await request.get_data()
    data = {}
    for a in rawData.decode().split("&"):
        v = a.split("=")
        data[v[0]] = v[1]

    Thread(target=aRun, args=(lockChannel(data),), daemon=True).start()

    return "", 200


if __name__ == "__main__":
    quartApp.run(host="0.0.0.0", port=65099)
    print()
