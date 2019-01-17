#!/usr/bin/env python3

#
# This is file `twoot.py'.
#
# Copyright 2018 Takuto ASAKURA (wtsnjp)
#   GitHub:   https://github.com/wtsnjp
#   Twitter:  @wtsnjp
#   Mastodon: @wtsnjp@mstdn.jp
#
# This software is distributed under the MIT License.
#

PROG_NAME = "twoot.py"
HELP = """Sync Twitter and Mastodon nicely.

Usage:
    {p} [options]

Options:
    -d, --debug              Show debug messages.
    -h, --help               Show this screen and exit.
    -l FILE, --log=FILE      Output messages to FILE.
    -n, --dry-run            Show what would have been transferred.
    -p NAME, --profile=NAME  Use profile NAME.
    -q, --quiet              Show less messages.
    -s, --setup              Execute setup mode.
    -u, --update             Update data (only effective with -n).
    -v, --version            Show version.
""".format(p=PROG_NAME)
VERSION = "1.1.0"

# basic libraries
import os
import re
import json
import fcntl
import pickle
from getpass import getpass
from urllib.parse import urlparse

# pypi libraries
from docopt import docopt
from mastodon import Mastodon
import twitter as Twitter
import html2text
import requests

# use logger
import logging as log
from logging.handlers import RotatingFileHandler
logger = log.getLogger('twoot')


# the module
class Twoot:
    def __app_questions(self):
        # defaults
        d_name = 'twoot.py'
        d_url = 'https://github.com/wtsnjp/twoot.py'

        # ask questions
        print('\n#1 First, decide about your application.')

        name = input('Name (optional; empty for "{}"): '.format(d_name))
        url = input('Website (optional; empty for "{}"): '.format(d_url))

        # set config
        if len(name) < 1:
            name = d_name
        if len(url) < 1:
            url = d_url

        return name, url

    def __mastodon_questions(self, app_name, app_url):
        # ask questions
        print('\n#2 Tell me about your Mastodon account.')

        inst = input('Instance (e.g., https://mastodon.social): ').rstrip('/')
        mail = input('Login e-mail (never stored): ')
        pw = getpass(prompt='Login password (never stored): ')

        # register application
        cl_id, cl_sc = Mastodon.create_app(
            app_name, website=app_url, api_base_url=inst)

        # application certification & login
        mastodon = Mastodon(
            client_id=cl_id, client_secret=cl_sc, api_base_url=inst)
        access_token = mastodon.log_in(mail, pw)

        # set config
        self.config['mastodon'] = {
            'instance': inst,
            'access_token': access_token
        }

        return mastodon

    def __twitter_questions(self):
        # ask questions
        print('\n#3 Tell me about your Twitter account.')
        print(
            'cf. You can get keys and tokens from https://developer.twitter.com/'
        )

        cs_key = input('API key: ')
        cs_secret = input('API secret key: ')
        ac_tok = input('Access token: ')
        ac_sec = input('Access token secret: ')

        # OAuth
        auth = Twitter.OAuth(ac_tok, ac_sec, cs_key, cs_secret)
        twitter = Twitter.Twitter(auth=auth)

        # set config
        self.config['twitter'] = {
            'consumer_key': cs_key,
            'consumer_secret': cs_secret,
            'access_token': ac_tok,
            'access_token_secret': ac_sec
        }

        return twitter

    def __init__(self, profile='default', setup=False):
        # files
        twoot_dir = os.path.expanduser('~/.' + PROG_NAME)
        if not os.path.isdir(twoot_dir):
            os.mkdir(twoot_dir)
        logger.debug('Selected profile: ' + profile)
        self.config_file = twoot_dir + '/{}.json'.format(profile)
        self.data_file = twoot_dir + '/{}.pickle'.format(profile)

        # config
        if setup or not os.path.isfile(self.config_file):
            # setup mode
            logger.debug('Selected mode: setup')
            self.setup = True

            # initialize
            self.config = {'max_twoots': 1000}

            # ask for config entries
            print('Welcome to Twoot! Please answer a few questions.')
            app_name, app_url = self.__app_questions()
            self.mastodon = self.__mastodon_questions(app_name, app_url)
            self.twitter = self.__twitter_questions()

            print('\nAll configuration done. Thanks!')

            # save config
            logger.debug('Saving current config to {}'.format(
                self.config_file))
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4, sort_keys=True)

        else:
            # normal mode
            logger.debug('Selected mode: normal')
            self.setup = False

            # load config
            logger.debug('Loading config file {}'.format(self.config_file))
            with open(self.config_file) as f:
                self.config = json.loads(f.read(), 'utf-8')

            # setup Mastodon
            ms = self.config['mastodon']
            self.mastodon = Mastodon(
                access_token=ms['access_token'], api_base_url=ms['instance'])

            # setup Twitter
            tw = self.config['twitter']
            t_auth = Twitter.OAuth(tw['access_token'],
                                   tw['access_token_secret'],
                                   tw['consumer_key'], tw['consumer_secret'])
            self.twitter = Twitter.Twitter(auth=t_auth)
            self.twitter_upload = Twitter.Twitter(
                domain='upload.twitter.com', auth=t_auth)

        # data
        self.twoots = []

        if os.path.isfile(self.data_file):
            logger.debug('Loading data file {}'.format(self.data_file))
            with open(self.data_file, 'rb') as f:
                self.data = pickle.load(f)
        else:
            logger.debug('No data file found; initialzing')
            self.data = {'twoots': []}

        # fetch self account information
        if not self.data.get('mastodon_account', False):
            try:
                logger.debug(
                    'Fetching Mastodon account information (verify credentials)'
                )
                self.data[
                    'mastodon_account'] = self.mastodon.account_verify_credentials(
                    )
            except Exception as e:
                logger.exception(
                    'Failed to verify credentials for Mastodon: {}'.format(e))
                logger.critical('Unable to continue; abort!')
                raise

        if not self.data.get('twitter_account', False):
            try:
                logger.debug(
                    'Fetching Twitter account information (verify credentials)'
                )
                self.data[
                    'twitter_account'] = self.twitter.account.verify_credentials(
                    )
            except Exception as e:
                logger.exception(
                    'Failed to verify credentials for Twitter: {}'.format(e))
                logger.critical('Unable to continue; abort!')
                raise

        # utility
        self.html2text = html2text.HTML2Text()
        self.html2text.body_width = 0

    def __update_last_id(self, key, value):
        """Update the last id (last_toot or last_tweet) in the data file."""
        # load the latest data
        if os.path.isfile(self.data_file):
            with open(self.data_file, 'rb') as f:
                data = pickle.load(f)
        else:
            data = {'twoots': []}

        # update the target
        data[key] = value
        with open(self.data_file, 'wb') as f:
            pickle.dump(data, f)

    def get_new_toots(self, dry_run=False, update=False):
        """Get new toots of the author.

        Using account_statuses API, get the author's new toots, i.e., the toots
        from the owner's account since the last toot id, and return the list of
        toot dicts. If the last toot id cannot be found in the data, the id of
        latest toot is recoreded and return an empty list.

        Returns:
            list: toot dicts
        """
        res = []

        # fetch necessary information
        my_id = self.data['mastodon_account']['id']
        last_id = self.data.get('last_toot', False)

        # try to get toots
        try:
            # get toots for sync
            if last_id:
                logger.debug('Getting new toots for sync')
                r = self.mastodon.account_statuses(my_id, since_id=last_id)

                logger.debug('Number of new toots: {}'.format(len(r)))
                res = r

            # get toots only for updating last_toot
            else:
                logger.debug('Getting new toots only for fetching information')
                r = self.mastodon.account_statuses(my_id)

            # update the last toot ID
            if len(r) > 0:
                new_last_id = r[0]['id']  # r[0] is the latest

                # update the data file immediately
                if not dry_run or update:
                    logger.debug(
                        'Updating the last toot: {}'.format(new_last_id))
                    self.__update_last_id('last_toot', new_last_id)

        except Exception as e:
            logger.exception('Failed to get new toots: {}'.format(e))

        return res

    def get_new_tweets(self, dry_run=False, update=False):
        """Get new tweets of the author.

        Using statuses/user_timeline API, get the author's new tweets, i.e.,
        the tweets from the owner's account since the last tweet id, and return
        the list of Tweet dicts. If the last tweet id cannot be found in the
        data, the id of latest tweet is recoreded and return an empty list.

        Returns:
            list: toot dicts
        """
        res = []

        # fetch necessary information
        my_id = self.data['twitter_account']['id']
        last_id = self.data.get('last_tweet', False)

        # try to get tweets
        try:
            # get tweets for sync
            if last_id:
                logger.debug('Getting new tweets for sync')
                r = self.twitter.statuses.user_timeline(
                    user_id=my_id, since_id=last_id, tweet_mode="extended")

                logger.debug('Number of new tweets: {}'.format(len(r)))
                res = r

            # get tweets only for updating last_tweet
            else:
                logger.debug(
                    'Getting new tweets only for fetching information')
                r = self.twitter.statuses.user_timeline(
                    user_id=my_id, tweet_mode="extended")

            # update the last tweet ID
            if len(r) > 0:
                new_last_id = r[0]['id']  # r[0] is the latest

                # update the data file immediately
                if not dry_run or update:
                    logger.debug(
                        'Updating the last tweet: {}'.format(new_last_id))
                    self.__update_last_id('last_tweet', new_last_id)

        except Exception as e:
            logger.exception('Failed to get new tweets: {}'.format(e))

        return res

    def __store_twoot(self, toot_id, tweet_id):
        """Store a twoot (a pair of toot_id and tweet_id) in the data.

        Insert the newest twoot to the HEAD of data['twoot'].
        This is because it makes it easier to keep the number of stored twoots
        less than max_twoots and also efficient in searching calculation.
        """
        twoot = {'toot_id': toot_id, 'tweet_id': tweet_id}
        logger.debug('Storing a twoot: {}'.format(twoot))
        self.twoots.insert(0, twoot)

    def __find_paired_toot(self, tweet_id):
        """Returns the id of paired toot of `tweet_id`.

        Args:
            tweet_id (int): Id of a tweet

        Returns:
            int: Id of the paired toot of `tweet_id`
        """
        for t in self.twoots + self.data['twoots']:
            if t['tweet_id'] == tweet_id:
                toot_id = t['toot_id']
                return toot_id

        return None

    def __find_paired_tweet(self, toot_id):
        """Returns the id of paired tweet of `toot_id`.

        Args:
            toot_id (int): Id of a toot

        Returns:
            int: Id of the paired tweet of `toot_id`
        """
        for t in self.twoots + self.data['twoots']:
            if t['toot_id'] == toot_id:
                tweet_id = t['tweet_id']
                return tweet_id

        return None

    def __html2text(self, html):
        """Convert html to text.

        This process is essential for treating toots because the API of
        Mastodon give us a toot in HTML format. This conversion is also useful
        for tweets sometime because some specific letters (e.g., '<' and '>')
        are encoded in character references of HTML even for the Twitter API.

        Args:
            html (str): a html text

        Returns:
            str: the plain text
        """
        # prevent removing line break & char escapes
        escapeable = [
            ('\n', '<br>'),  # line break
            ('\\', '&#92;'),  # backslash
            ('+', '&#43;'),  # plus
            ('-', '&#45;'),  # hyphen
            ('.', '&#46;'),  # period
        ]
        for p in escapeable:
            html = html.replace(p[0], p[1])

        # basically, trust html2text
        text = self.html2text.handle(html).strip()

        # treat links and hashtags
        text = re.sub(r'\[#(.*?)\]\(.*?\)', r'#\1', text)
        text = re.sub(r'\[.*?\]\((.*?)\)', r'\1', text)

        return text

    def __pre_process(self, text, remove_words=[]):
        """Format a text nicely before posting.

        This function do four things:

            1. convert HTML to plain text
            2. expand shorten links
            3. remove given `remove_words` such as links of attached media
            4. delete tailing spaces

        Args:
            text (str): the text
            remove_words (str): the list of words to remove

        Returns:
            str: the pre-processed text
        """
        # process HTML tags/escapes
        text = self.__html2text(text)

        # expand links
        links = [w for w in text.split() if urlparse(w.strip()).scheme]

        for l in links:
            # check the link
            if not re.match(r'http(s|)://', l):
                continue

            # expand link with HTTP(S) HEAD request
            try:
                r = requests.head(l)
                url = r.headers.get('location', l)
                text = text.replace(l, url)

            except Exception as e:
                logger.exception('HTTP(S) HEAD request failed: {}'.format(e))

        # remove specified words
        for w in remove_words:
            text = text.replace(w, '')

        # no tailing spaces
        text = re.sub(r'[ \t]+\n', r'\n', text).strip()

        return text

    def __download_image(self, url):
        """Download an image from `url`.

        Args:
            url (str): the image url

        Returns:
            raw binary data
        """
        r = requests.get(url)
        if r.status_code != 200:
            logger.warn('Failed to get an image from {}'.format(url))
            return None

        c_type = r.headers['content-type']
        if 'image' not in c_type:
            logger.warn('Data from {} is not an image'.format(url))
            return None

        return r.content, c_type

    def __post_media_to_mastodon(self, media):
        """Get actual data of `media` from Twitter and post it to Mastodon.

        Args:
            media: a Twitter media dict

        Returns:
            a Mastodon media dict
        """
        img, mime_type = self.__download_image(media['media_url_https'])

        try:
            r = self.mastodon.media_post(img, mime_type=mime_type)

            # NOTE: only under development
            #logger.debug('Recieved media info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to post an image: {}'.format(e))
            return None

    def __toot(self, text, in_reply_to_id=None, media_ids=None):
        try:
            r = self.mastodon.status_post(
                text, in_reply_to_id=in_reply_to_id, media_ids=media_ids)

            # NOTE: only under development
            #logger.debug('Recieved toot info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to create a toot: {}'.format(e))
            return None

    def __boost(self, target_id):
        try:
            r = self.mastodon.status_reblog(target_id)

            # NOTE: only under development
            #logger.debug('Recieved toot (BT) info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to create a toot (BT): {}'.format(e))
            return None

    def create_toot_from_tweet(self, tweet, dry_run=False):
        """Create a toot corresponding to the tweet.

        Try to create a toot (or BT) if `tweet` satisfy:

            1. normal tweet
            2. so-called "self retweet" (create a corresponding BT)
            3. so-called "self reply" (create a corresponding thread)

        Otherwise, the tweet will be just skipped. In case `dry_run` is True,
        the actual post will never executed but only the messages are output.

        Args:
            tweet: a tweet dict
            dry_run (bool): the flag
        """
        my_id = self.data['twitter_account']['id']
        tweet_id = tweet['id']
        synced_tweets = [
            t['tweet_id'] for t in self.twoots + self.data['twoots']
        ]

        # skip if already forwarded
        if tweet_id in synced_tweets:
            logger.debug(
                'Skipping a tweet (id: {}) because it is already forwarded'.
                format(tweet_id))
            return

        # reply case; a bit complecated
        in_reply_to_tweet_id = None
        in_reply_to_user_id = tweet.get('in_reply_to_user_id', None)
        user_mentions = tweet.get('entities', {}).get('user_mentions', [])

        if in_reply_to_user_id:
            # skip reply for other users
            if in_reply_to_user_id != my_id or len(user_mentions) > 1:
                logger.debug(
                    'Skipping a tweet (id: {}) because it is a reply for other users'.
                    format(tweet_id))
                return

            # if self reply, store in_reply_to_tweet_id because possibly creating a thread
            logger.debug('The tweet (id: {}) is a self reply'.format(tweet_id))
            in_reply_to_tweet_id = tweet['in_reply_to_status_id']

        # RT case; more complecated
        retweeted_tweet = tweet.get('retweeted_status', None)

        if retweeted_tweet:
            retweeted_tweet_id = retweeted_tweet['id']

            # if self RT of a synced tweet, exec BT on the paired toot
            if retweeted_tweet_id in synced_tweets:
                target_toot_id = self.__find_paired_toot(retweeted_tweet_id)
                logger.debug('Boost a toot (id: {})'.format(target_toot_id))

                # execute BT
                if not dry_run:
                    r = self.__boost(target_toot_id)

                    if r:
                        toot_id = r['id']
                        self.__store_twoot(toot_id, tweet_id)

                # no more process for RT
                return

            # otherwise, just skip
            else:
                logger.debug(
                    'Skipping a tweet (id: {}) because it is an RT'.format(
                        tweet_id))
                return

        # treat media
        twitter_media = tweet.get('extended_entities', {}).get('media', [])
        media_num = 0

        # if dry run, don't upload
        if dry_run:
            media_num = len(twitter_media)

        else:
            mastodon_media = [
                self.__post_media_to_mastodon(m) for m in twitter_media
            ]
            media_ids = [m['id'] for m in mastodon_media if m is not None]
            media_num = len(media_ids)

        # treat text
        media_urls = [m['expanded_url'] for m in twitter_media]
        text = self.__pre_process(tweet['full_text'], remove_words=media_urls)

        # try to create a toot
        if media_num > 0:
            logger.debug('Trying to toot: {} (with {} media)'.format(
                repr(text), media_num))
        else:
            logger.debug('Trying to toot: {}'.format(repr(text)))

        if not dry_run:
            # NOTE: this branches are not necessary, but for calculation efficiency
            # if the tweet is in a thread and in sync, copy as a thread
            if in_reply_to_tweet_id in synced_tweets:
                r = self.__toot(
                    text,
                    in_reply_to_id=self.__find_paired_toot(
                        in_reply_to_tweet_id),
                    media_ids=media_ids)

            # otherwise, just toot it
            else:
                r = self.__toot(text, media_ids=media_ids)

            # store the twoot
            if r:
                toot_id = r['id']
                self.__store_twoot(toot_id, tweet_id)

                logger.info(
                    'Forwarded a tweet (id: {}) as a toot (id: {})'.format(
                        tweet_id, toot_id))

    def __post_media_to_twitter(self, media):
        """Get actual data of `media` from Mastodon and post it to Twitter.

        Args:
            media: a Mastodon media dict

        Returns:
            a Twitter media dict
        """
        img, mime_type = self.__download_image(media['url'])

        try:
            r = self.twitter_upload.media.upload(media=img)

            # NOTE: only under development
            #logger.debug('Recieved media info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to post an image: {}'.format(e))
            return None

    def __tweet(self, text, in_reply_to_id=None, media_ids=None):
        try:
            r = self.twitter.statuses.update(
                status=text,
                in_reply_to_status_id=in_reply_to_id,
                media_ids=','.join(media_ids))

            # NOTE: only under development
            #logger.debug('Recieved tweet info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to create a tweet: {}'.format(e))
            return None

    def __retweet(self, target_id):
        try:
            r = self.twitter.statuses.retweet(_id=target_id)

            # NOTE: only under development
            #logger.debug('Recieved toot (BT) info: {}'.format(str(r)))

            return r

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to create a tweet (RT): {}'.format(e))
            return None

    def create_tweet_from_toot(self, toot, dry_run=False):
        """Create a tweet corresponding to the toot.

        Try to create a tweet (or RT) if `toot` satisfy:

            1. normal toot
            2. so-called "self boost" (create a corresponding RT)
            3. so-called "self reply" (create a corresponding thread)

        Otherwise, the toot will be just skipped. In case `dry_run` is True,
        the actual post will never executed but only the messages are output.

        Args:
            toot: a toot dict
            dry_run (bool): the flag
        """
        my_id = self.data['mastodon_account']['id']
        toot_id = toot['id']
        synced_toots = [
            t['toot_id'] for t in self.twoots + self.data['twoots']
        ]

        # skip if already forwarded
        if toot_id in synced_toots:
            logger.debug(
                'Skipping a toot (id: {}) because it is already forwarded'.
                format(toot_id))
            return

        # reply case; a bit complecated
        in_reply_to_toot_id = None
        in_reply_to_account_id = toot['in_reply_to_account_id']

        if in_reply_to_account_id:
            # skip reply for other users
            if in_reply_to_account_id != my_id:
                logger.debug(
                    'Skipping a toot (id: {}) because it is a reply for other users'.
                    format(toot_id))
                return

            # if self reply, store in_reply_to_toot_id because possibly creating a thread
            logger.debug('The toot (id: {}) is a self reply'.format(toot_id))
            in_reply_to_toot_id = toot['in_reply_to_id']

        # BT case; more complecated
        boosted_toot = toot.get('reblog', None)

        if boosted_toot:
            boosted_toot_id = boosted_toot['id']

            # if self BT of a synced toot, exec RT on the paired tweet
            if boosted_toot_id in synced_toots:
                target_tweet_id = self.__find_paired_tweet(boosted_toot_id)
                logger.debug(
                    'Retweet a tweet (id: {})'.format(target_tweet_id))

                # execute RT
                if not dry_run:
                    r = self.__retweet(target_tweet_id)

                    if r:
                        tweet_id = r['id']
                        self.__store_twoot(toot_id, tweet_id)

                # no more process for BT
                return

            # otherwise, just skip
            else:
                logger.debug(
                    'Skipping a toot (id: {}) because it is a BT'.format(
                        toot_id))
                return

        # treat media
        mastodon_media = toot.get('media_attachments', [])
        media_num = 0

        # if dry run, don't upload
        if dry_run:
            media_num = len(mastodon_media)

        else:
            twitter_media = [
                self.__post_media_to_twitter(m) for m in mastodon_media
            ]
            media_ids = [
                m['media_id_string'] for m in twitter_media if m is not None
            ]
            media_num = len(media_ids)

        # treat text
        text = self.__pre_process(toot['content'])

        # try to create a tweet
        if media_num > 0:
            logger.debug('Trying to tweet: {} (with {} media)'.format(
                repr(text), media_num))
        else:
            logger.debug('Trying to tweet: {}'.format(repr(text)))

        if not dry_run:
            # NOTE: this branches are not necessary, but for calculation efficiency
            # if the toot is in a thread and in sync, copy as a thread
            if in_reply_to_toot_id in synced_toots:
                r = self.__tweet(
                    text,
                    in_reply_to_id=self.__find_paired_tweet(
                        in_reply_to_toot_id),
                    media_ids=media_ids)

            # otherwise, just tweet it
            else:
                r = self.__tweet(text, media_ids=media_ids)

            # store the twoot
            if r:
                tweet_id = r['id']
                self.__store_twoot(toot_id, tweet_id)

                logger.info(
                    'Forwarded a toot (id: {}) as a tweet (id: {})'.format(
                        toot_id, tweet_id))

    def tweets2toots(self, tweets, dry_run=False):
        # process from the oldest one
        for t in reversed(tweets):
            # NOTE: only under development
            #logger.debug('Processing tweet info: {}'.format(t))

            # create a toot if necessary
            self.create_toot_from_tweet(t, dry_run)

    def toots2tweets(self, toots, dry_run=False):
        # process from the oldest one
        for t in reversed(toots):
            # NOTE: only under development
            #logger.debug('Processing toot info: {}'.format(t))

            # create a toot if necessary
            self.create_tweet_from_toot(t, dry_run)

    def __save_data(self):
        """Save up-to-dated data (twoots) to the data file."""
        # load the latest data
        with open(self.data_file, 'rb') as f:
            data = pickle.load(f)

        # concat the new twoots to data
        data['twoots'] = self.twoots + data['twoots']

        # keep the number of stored twoots less than max_twoots
        data['twoots'] = data['twoots'][:self.config['max_twoots']]

        # save data
        with open(self.data_file, 'wb') as f:
            pickle.dump(data, f)

    def run(self, dry_run=False, update=False):
        if dry_run:
            if self.setup:
                logger.warn(
                    'Option --dry-run (-n) has no effect for setup mode')
                dry_run = False
            else:
                logger.debug('Dry running')
        else:
            logger.debug('Running')

        # tweets -> toots
        toots = self.get_new_toots(dry_run, update)
        if not self.setup:
            self.toots2tweets(toots, dry_run)

        # toots -> tweets
        tweets = self.get_new_tweets(dry_run, update)
        if not self.setup:
            self.tweets2toots(tweets, dry_run)

        # update the entire data
        if len(self.twoots) > 0:
            logger.debug('Saving up-to-dated data to {}'.format(
                self.data_file))
            self.__save_data()


# the application
def set_logger(log_level, log_file):
    # log level
    if log_level == 0:
        level = log.WARN
    elif log_level == 2:
        level = log.DEBUG
    else:
        level = log.INFO

    # log file
    if log_file:
        handler = RotatingFileHandler(
            log_file, maxBytes=5000000, backupCount=9)
        formatter = log.Formatter(
            '%(asctime)s - %(name)s %(levelname)s: %(message)s')
    else:
        handler = log.StreamHandler()
        formatter = log.Formatter('%(name)s %(levelname)s: %(message)s')

    # apply settings
    handler.setLevel(level)
    handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False


def main():
    """The main function.

    1. parse command line options
    2. setup the logger
    3. execute twoot actions (make sure to be a singleton)
    """
    # parse options
    args = docopt(HELP, version=VERSION)
    setup = args['--setup']
    dry_run, update = args['--dry-run'], args['--update']
    profile = args['--profile'] or 'default'

    # setup the logger
    log_level = 1  # info (default)
    if args['--quiet']:
        log_level = 0  # warn
    if args['--debug']:
        log_level = 2  # debug

    log_file = args['--log']  # output messages stderr as default

    set_logger(log_level, log_file)

    # make sure to be a singleton
    lf = os.path.expanduser('~/.' + PROG_NAME + '/lockfile.lock')
    with open(lf, 'w') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

            # execute twoot actions
            twoot = Twoot(profile, setup)
            twoot.run(dry_run, update)

        except IOError:
            logger.debug('Process already exists')


if __name__ == '__main__':
    main()
