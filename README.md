# twoot.py (v1.5.0)

Sync Twitter and Mastodon nicely ― forward tweets to Mastodon and forward toots to Twitter, carefully not to make duplicate posts on a service. Other features of twoot.py are:

* images are also forwarded each other,
* sync so-called "thread" and "self BT/RT" as well,
* shortened URLs (such as `https://t.co/*`) are expanded before posting, and
* multiple pairs of Mastodon/Twitter accounts are supported.

## Requirements

This script is designed to work with Python (3.5 or later).

## Installation

All dependencies can be installed with:

```
$ python setup.py install
```

## Usage

### Setup running

After installing the script, run `twoot.py` once by hand and fill in the following fields:

```
$ python twoot.py
Welcome to Twoot! Please answer a few questions.

#1 First, decide about your application.
Name (optional; empty for "twoot.py"): 
Website (optional; empty for "https://github.com/wtsnjp/twoot.py"): 

#2 Tell me about your Mastodon account.
Instance (e.g., https://mastodon.social): 
Login e-mail (never stored): 
Login password (never stored): 

#3 Tell me about your Twitter account.
cf. You can get keys & tokens from https://developer.twitter.com/
API key: 
API secret key: 
Access token: 
Access token secret: 

All configuration done. Thanks!
```

When the setup mode is completed successfully, all necessary configurations will be stored under `$HOME/.twoot.py`. No toots nor tweets are sent within the setup mode.

> Note: If you want to change these configurations, execute `python twoot.py --setup` to start setup mode once again or just edit `$HOME/.twoot.py/default.json` directly.

### Regular running

After the setup running, set cron (or whatever) to run `python twoot.py` regularly, e.g., running every 15 sec:

```
* * * * * for i in `seq 0 15 59`;do (sleep ${i}; python /path/to/twoot.py --log=/path/to/twoot.log) & done;
```

### Using profile

You can detect a profile with the command line option `--profile` (`-p`) to use this script for multiple accounts. The configuration and the data for a profile `NAME` are saved to `~/.twoot.py/NAME.json` and `~/.twoot.py/NAME.pickle` respectively. When you omit the command line option, the "default" profile is automatically selected.

### Example configurations

See [example-config.json](./example-config.json).

## License

This software is distributed under [the MIT license](./LICENSE).

---

Takuto ASAKURA ([wtsnjp](https://github.com/wtsnjp))
