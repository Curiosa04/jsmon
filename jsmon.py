#!/usr/bin/env python3

import requests
import re
import os
import hashlib
import json
import difflib
import jsbeautifier

from decouple import config

TELEGRAM_TOKEN = config("JSMON_TELEGRAM_TOKEN", default="CHANGEME")
SLACK_TOKEN = config("JSMON_SLACK_TOKEN", default="CHANGEME")
NOTIFY_SLACK = config("JSMON_NOTIFY_SLACK", default=False, cast=bool)
NOTIFY_TELEGRAM = config("JSMON_NOTIFY_TELEGRAM", default=False, cast=bool)
JS_MON_DIR = os.environ['jsMonDir']
JS_MON_DATA = os.environ['jsMonDataDir']

# uncomment for testing
JS_MON_DIR = "{}/test".format(JS_MON_DATA)
JS_MON_DATA += "/test"

if NOTIFY_SLACK:
    from slack import WebClient
    from slack.errors import SlackApiError
    if(SLACK_TOKEN == "CHANGEME"):
        print("ERROR SLACK TOKEN NOT FOUND!")
        exit(1)
    client = WebClient(token=SLACK_TOKEN)


def is_valid_endpoint(endpoint):
    regex = re.compile(
        r'^(?:http|ftp)s?://'  # http:// or https://
        # domain...
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    # check if valid url
    return re.match(regex, endpoint) is not None


def get_target_data(endpointdir):
    data = []
    filenames = []
    for (dp, dirnames, files) in os.walk(endpointdir):
        filenames.extend(files)
    filenames = list(filter(lambda x: x[0] != ".", filenames))
    filenames = list(filter(lambda x: x != "example.json", filenames))
    for file in filenames:
        with open("{}/{}".format(endpointdir, file), "r") as f:
            data.append(json.load(f))

    for item in data:
        if NOTIFY_SLACK and item['slackChannelId'] == "":
            print(
                f"You enabled slack integration, but there's an empty slackChannelId in the JSON")
            exit(1)
        if NOTIFY_TELEGRAM and item['telegramChatId'] == "":
            print(
                f"You enabled telegram integration, but there's an empty telegramChatId in the JSON")
            exit(1)

    # Load all endpoints from a dir into a list
    return data


def get_endpoint(endpoint):
    # get an endpoint, return its content
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36'
        }
        r = requests.get(endpoint, headers=headers)
        return r.text
    except:
        print("Error while establishing connection")
        return None


def get_hash(string):
    # Hash a string
    return hashlib.md5(string.encode("utf8")).hexdigest()[:10]


def save_endpoint(endpoint, ephash, eptext):
    # save endpoint content to file
    # add it to  list of
    with open("{}/hashes.json".format(JS_MON_DIR), "r") as jsm:
        jsmd = json.load(jsm)
        if endpoint in jsmd.keys():
            jsmd[endpoint].append(ephash)
        else:
            jsmd[endpoint] = [ephash]

    with open("{}/hashes.json".format(JS_MON_DIR), "w") as jsm:
        json.dump(jsmd, jsm)

    with open("{}/downloads/{}".format(JS_MON_DATA, ephash), "w") as epw:
        epw.write(eptext)


def get_previous_endpoint_hash(endpoint):
    # get previous endpoint version
    # or None if doesnt exist
    with open("{}/hashes.json".format(JS_MON_DIR), "r") as jsm:
        jsmd = json.load(jsm)
        if endpoint in jsmd.keys():
            return jsmd[endpoint][-1]
        else:
            return None


def get_file_stats(fhash):
    return os.stat("{}/downloads/{}".format(JS_MON_DATA, fhash))


def get_diff(endpoint, old, new):
    opt = {
        "indent_with_tabs": 1,
        "keep_function_indentation": 0,
    }
    oldlines = open("{}/downloads/{}".format(JS_MON_DATA, old),
                    "r").readlines()
    newlines = open("{}/downloads/{}".format(JS_MON_DATA, new),
                    "r").readlines()
    oldbeautified = jsbeautifier.beautify("".join(oldlines), opt).splitlines()
    newbeautified = jsbeautifier.beautify("".join(newlines), opt).splitlines()
    # print(oldbeautified)
    # print(newbeautified)

    differ = difflib.HtmlDiff()
    html = differ.make_file(oldbeautified, newbeautified)
    lios = endpoint.rfind('/') + 1
    end = len(endpoint)
    fileName = endpoint[lios:end]
    formattedFileName = "{}.{}.html".format(new, fileName)
    open("{}/diff/{}".format(JS_MON_DATA, formattedFileName), "w").write(html)
    return formattedFileName


def notify_telegram(endpoint, chatId, prev, new, prevsize, newsize):
    print("[!!!] Endpoint [ {} ] has changed from {} to {}".format(
        endpoint, prev, new))
    log_entry = "{} has been updated from <code>{}</code>(<b>{}</b>Bytes) to <code>{}</code>(<b>{}</b>Bytes)".format(
        endpoint, prev, prevsize, new, newsize)
    payload = {
        'chat_id': chatId,
        'caption': log_entry,
        'parse_mode': 'HTML'
    }
    # fpayload = {
    #    'document': ('diff.html', diff)
    # }

    # sendfile = requests.post("https://api.telegram.org/bot{token}/sendDocument".format(token=TELEGRAM_TOKEN),
    #                        files=fpayload, data=payload)
    sendfile = requests.post("https://api.telegram.org/bot{token}/sendDocument".format(token=TELEGRAM_TOKEN),
                             data=payload)
    # print(sendfile.content)
    return sendfile


def notify_slack(endpoint, slackChannelId, prevsize, newsize, diffFileName):
    try:
        response = client.chat_postMessage(
            text="[JSmon] {} has been updated from {} Bytes to {} Bytes. Diff file name: {}".format(endpoint, prevsize, newsize, diffFileName),
            channel=slackChannelId
        )
        return response
    except SlackApiError as e:
        assert e.response["ok"] is False
        # str like 'invalid_auth', 'channel_not_found'
        assert e.response["error"]
        print(f"Got an error: {e.response['error']}")


def notify(endpoint, slackChannelId, telegramChatId, prev, new):
    filename = get_diff(endpoint, prev, new)

    prevsize = get_file_stats(prev).st_size
    newsize = get_file_stats(new).st_size
    if NOTIFY_TELEGRAM:
        notify_telegram(endpoint, telegramChatId, prev,
                        new, prevsize, newsize)

    if NOTIFY_SLACK:
        notify_slack(endpoint, slackChannelId, prevsize, newsize, filename)


def main():
    print("JSMon - Web File Monitor")

    if not(NOTIFY_SLACK or NOTIFY_TELEGRAM):
        print("You need to setup Slack or Telegram Notifications of JSMon to work!")
        exit(1)
    if NOTIFY_TELEGRAM and "CHANGEME" in [TELEGRAM_TOKEN]:
        print("Please Set Up your Telegram Token And Chat ID!!!")

    allTargets = get_target_data(JS_MON_DIR + "/targets")

    for target in allTargets:
        for fullEndpoint in target['endpoints']:
            endpoint = fullEndpoint
            if 'mask' in target:
                endpoint = re.sub(target['mask'], "", fullEndpoint)
            print("Checking endpoint " + endpoint)

            prev_hash = get_previous_endpoint_hash(endpoint)
            ep_text = get_endpoint(fullEndpoint)
            if ep_text == None:
                continue

            ep_hash = get_hash(ep_text)
            if ep_hash == prev_hash:
                print("No file change detected")
                continue
            else:
                save_endpoint(endpoint, ep_hash, ep_text)
                if prev_hash is not None:
                    print("File change detected!")
                    notify(endpoint, target['slackChannelId'],
                           target['telegramChatId'], prev_hash, ep_hash)
                else:
                    print("New Endpoint enrolled: {}".format(endpoint))


main()
