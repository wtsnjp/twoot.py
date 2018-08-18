# twoot.py (v0.1.0)

Sync Twitter and Mastodon nicely ― forward tweets to Mastodon and forward toots to Twitter, carefully not to make duplicate posts on a service.

## Requirements

This script is designed to work with Python3 (3.5 or later).

## Installation

All dependencies can be installed by one shot:

```
$ python3 setup.py install
```

## Usage

After installing the script, run it once by yourself to fill the following fields:

```
$ python3 twoot.py
Welcome to Twoot! Please answer a few questions.

#1 First, decide about your application.
Name (optional; empty for "Twoot"):
Redirect URL (optional; empty for "https://github.com/wtsnjp/twoot.py"):

#2 Tell me about your Mastodon account.
Instance (e.g., https://mastodon.social): 
Login e-mail (never stored): 
Login password (never stored):

#3 Tell me about your Twitter account.
cf. Keys and tokens can be get from https://developer.twitter.com/
API key: 
API secret key: 
Access token: 
Access token secret: 
```

When this setup run is completed successfully, all necessary configuration will be stored under `$HOME/.twoot.py`. No toots nor tweets are sent by setup run.

> Note: If you want to change these configuration, delete `$HOME/.twoot.py` to execute the setup run again or just edit `$HOME/.twoot.py/config.json` directly.

After the setup run, setup cron (or whatever) to run `python3 twoot.py` regularly, e.g., running every 15 sec:

```
* * * * * for i in `seq 0 15 59`;do (sleep ${i}; python3 twoot.py) & done;
```

## License

This software is distributed under [the MIT license](./LICENSE).

---

Takuto ASAKURA ([wtsnjp](https://github.com/wtsnjp))
