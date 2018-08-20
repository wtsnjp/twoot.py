#!/usr/bin/env python3

#
# This is file `twoot.py'.
#
# Copyright (c) 2018 Takuto ASAKURA (wtsnjp)
#   GitHub:   https://github.com/wtsnjp
#   Twitter:  @wtsnjp
#   Mastodon: @wtsnjp@mstdn.jp
#
# This software is distributed under the MIT License.
#

PROG_NAME = "twoot.py"
HELP = """
Sync Twitter and Mastodon nicely

Usage:
    {} [options]

Options:
    -d, --debug          Show debug messages.
    -h, --help           Show this screen and exit.
    -l FILE, --log=FILE  Output messages to FILE.
    -n, --dry-run        Show what would have been transferred.
    -q, --quiet          Show less messages.
    -s, --setup          Execute setup mode.
    -v, --version        Show version.

""".format(PROG_NAME)
VERSION = "0.1.0"

# basic libraries
import os
import re
import json
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
        d_name = 'Twoot'
        d_url = None

        # ask questions
        print('\n#1 First, decide about your application.')

        name = input('Name (optional; empty for "{}"): '.format(d_name))
        url = input('Redirect URL (optional): ')

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
        # TODO: register application redirect url
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

    def __init__(self, setup=False):
        # files
        twoot_dir = os.path.expanduser('~/.' + PROG_NAME)
        if not os.path.isdir(twoot_dir):
            os.mkdir(twoot_dir)
        self.config_file = twoot_dir + '/config.json'
        self.data_file = twoot_dir + '/data.pickle'

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

        # data
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
                    'Fetch your Mastodon account information (verify credentials)'
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
                    'Fetch your Twitter account information (verify credentials)'
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

    def get_new_toots(self):
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
                logger.debug('Updating the last toot: {}'.format(new_last_id))
                self.data['last_toot'] = new_last_id

        except Exception as e:
            logger.exception('Failed to get new toots: {}'.format(e))

        return res

    def get_new_tweets(self):
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
                logger.debug('Updating the last tweet: {}'.format(new_last_id))
                self.data['last_tweet'] = new_last_id

        except Exception as e:
            logger.exception('Failed to get new tweets: {}'.format(e))

        return res

    def __store_twoot(self, toot_id, tweet_id):
        # store the twoot
        twoot = {'toot_id': toot_id, 'tweet_id': tweet_id}
        logger.debug('Storing a twoot: {}'.format(twoot))
        self.data['twoots'].append(twoot)

        # the number of stored twoots should <= max_twoots
        if len(self.data['twoots']) > self.config['max_twoots']:
            self.data['twoots'].pop(0)

    def __find_paired_toot(self, tweet_id):
        for t in self.data['twoots']:
            if t['tweet_id'] == tweet_id:
                toot_id = t['toot_id']
                return toot_id

        return None

    def __find_paired_tweet(self, toot_id):
        for t in self.data['twoots']:
            if t['toot_id'] == toot_id:
                tweet_id = t['tweet_id']
                return tweet_id

        return None

    def __html2text(self, html):
        # basically, trust html2text
        text = self.html2text.handle(html).strip()

        # treat links and hashtags
        text = re.sub(r'\[#(.*?)\]\(.*?\)', r'#\1', text)
        text = re.sub(r'\[.*?\]\((.*?)\)', r'\1', text)

        return text

    def __pre_process(self, text):
        # process HTML tags/escapes
        text = self.__html2text(text)

        # no endline spaces
        # TODO: is this necessary?
        text = re.sub(r'[ \t]+\n', r'\n', text)

        # expand links
        links = [w for w in text.split() if urlparse(w.strip()).scheme]

        for l in links:
            r = requests.head(l)
            url = r.headers.get('location', l)
            text = text.replace(l, url)

        return text

    def __create_toot_from_tweet(self, tweet, dry_run=False):
        tweet_id = tweet['id']
        text = self.__pre_process(tweet['full_text'])
        synced_tweets = [t['tweet_id'] for t in self.data['twoots']]

        in_reply_to_tweet_id = None
        in_reply_to_user_id = tweet['in_reply_to_user_id']
        my_id = self.data['twitter_account']['id']

        # skip if already forwarded
        if tweet_id in synced_tweets:
            logger.debug(
                'Skipping a tweet (id: {}) because it is already forwarded'.
                format(tweet_id))
            return

        # reply cases; a bit complecated
        elif in_reply_to_user_id:
            # skip reply for other users
            if in_reply_to_user_id != my_id:
                logger.debug(
                    'Skipping a tweet (id: {}) because it is a reply for other users'.
                    format(tweet_id))
                return

            # if self reply, store in_reply_to_tweet_id because possibly creating a thread
            logger.debug('The tweet (id: {}) is a self reply'.format(tweet_id))
            in_reply_to_tweet_id = tweet['in_reply_to_status_id']

        # try to create a toot
        logger.debug('Trying to toot: {}'.format(repr(text)))

        # if dry run, terminate here
        if dry_run:
            return

        # the big casino; posting
        try:
            # NOTE: this branches are not necessary, but for calculation efficiency
            # if the tweet is in a thread and in sync, copy as a thread
            if in_reply_to_tweet_id in synced_tweets:
                r = self.mastodon.status_post(
                    text,
                    in_reply_to_id=self.__find_paired_toot(
                        in_reply_to_tweet_id))

            # otherwise, just toot it
            else:
                r = self.mastodon.status_post(text)

            # NOTE: only under development
            #logger.debug('Recieved toot info: {}'.format(str(r)))

            toot_id = r['id']
            self.__store_twoot(toot_id, tweet_id)

            logger.info('Forwarded a tweet (id: {}) as a toot (id: {})'.format(
                tweet_id, toot_id))

        # if failed, report it
        except Exception as e:
            logger.exception('Failed to create a toot: {}'.format(e))

    def __create_tweet_from_toot(self, toot, dry_run=False):
        toot_id = toot['id']
        text = self.__pre_process(toot['content'])
        synced_toots = [t['toot_id'] for t in self.data['twoots']]

        in_reply_to_toot_id = None
        in_reply_to_account_id = toot['in_reply_to_account_id']
        my_id = self.data['mastodon_account']['id']

        # skip if already forwarded
        if toot_id in synced_toots:
            logger.debug(
                'Skipping a toot (id: {}) because it is already forwarded'.
                format(toot_id))
            return

        # reply cases; a bit complecated
        elif in_reply_to_account_id:
            # skip reply for other users
            if in_reply_to_account_id != my_id:
                logger.debug(
                    'Skipping a toot (id: {}) because it is a reply for other users'.
                    format(toot_id))
                return

            # if self reply, store in_reply_to_toot_id because possibly creating a thread
            logger.debug('The toot (id: {}) is a self reply'.format(toot_id))
            in_reply_to_toot_id = toot['in_reply_to_id']

        # try to create a tweet
        logger.debug('Trying to tweet: {}'.format(repr(text)))

        # if dry run, terminate here
        if dry_run:
            return

        # the big casino; posting
        # TODO: just uncomment these after getting consumer keys officially
        #try:
        #    # NOTE: this branches are not necessary, but for calculation efficiency
        #    # if the toot is in a thread and in sync, copy as a thread
        #    if in_reply_to_toot_id in synced_toots:
        #        r = self.twitter.status.update(
        #            status=text,
        #            in_reply_to_status_id=self.__find_paired_tweet(
        #                in_reply_to_toot_id))
        #
        #    # otherwise, just toot it
        #    else:
        #        r = self.twitter.status.update(status=text)
        #    # NOTE: only under development
        #    logger.debug('Recieved tweet info: {}'.format(str(r)))
        #
        #    tweet_id = r['id']
        #    self.__store_twoot(toot_id, tweet_id)
        #
        #    logger.info('Forwarded a toot (id: {}) as a tweet (id: {})'.format(
        #        toot_id, tweet_id))
        #
        ## if failed, report it
        #except Exception as e:
        #    logger.exception('Failed to create a tweet: {}'.format(e))

    def tweets2toots(self, tweets, dry_run=False):
        for t in reversed(tweets):
            # NOTE: only under development
            #logger.debug('Processing tweet info: {}'.format(t))

            # create a toot if necessary
            self.__create_toot_from_tweet(t, dry_run)

    def toots2tweets(self, toots, dry_run=False):
        for t in reversed(toots):
            # NOTE: only under development
            #logger.debug('Processing toot info: {}'.format(t))

            # create a toot if necessary
            self.__create_tweet_from_toot(t, dry_run)

    def run(self, dry_run=False):
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
        toots = self.get_new_toots()
        if not self.setup:
            self.toots2tweets(toots, dry_run)

        # toots -> tweets
        tweets = self.get_new_tweets()
        if not self.setup:
            self.tweets2toots(tweets, dry_run)

        # save data
        if not dry_run:
            logger.debug('Saving latest data to {}'.format(self.data_file))
            with open(self.data_file, 'wb') as f:
                pickle.dump(self.data, f)


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
    """
    The main function:

        1. parse command line options
        2. setup the logger
        3. execute twoot actions
    """
    # parse options
    args = docopt(HELP, version=VERSION)
    setup, dry_run = args['--setup'], args['--dry-run']

    # setup the logger
    log_level = 1  # info (default)
    if args['--quiet']:
        log_level = 0  # warn
    if args['--debug']:
        log_level = 2  # debug

    log_file = args['--log']  # output messages stderr as default

    set_logger(log_level, log_file)

    # execute twoot actions
    twoot = Twoot(setup)
    twoot.run(dry_run)


if __name__ == '__main__':
    main()
