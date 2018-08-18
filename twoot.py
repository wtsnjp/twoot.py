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

import os
import re
import json
import codecs
import getpass
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from mastodon import Mastodon
import twitter as Twitter
import html2text
import requests


def main():
    twoot = Twoot()
    twoot.run()


def get_logger(name):
    logger = logging.getLogger(name)
    handler = RotatingFileHandler('twoot.log', maxBytes=5000000, backupCount=9)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    level = logging.INFO

    handler.setLevel(level)
    handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False

    return logger


class Twoot:
    logger = get_logger('twoot')

    def __app_questions(self):
        # defaults
        d_name = 'Twoot'
        d_url = 'https://github.com/wtsnjp/twoot.py'

        # ask questions
        print('\n#1 First, decide about your application.')

        name = input('Name (optional; empty for "{}"): '.format(d_name))
        url = input('Redirect URL (optional; empty for "{}"): '.format(d_url))

        # set config
        if len(name) < 1:
            name = d_name
        if len(url) < 1:
            url = d_url

        self.config['app'] = {'name': name, 'url': url}

    def __mastodon_questions(self):
        # ask questions
        print('\n#2 Tell me about your Mastodon account.')

        inst = input('Instance (e.g., https://mastodon.social): ').rstrip('/')
        mail = input('Login e-mail (never stored): ')
        pw = getpass.getpass(prompt='Login password (never stored): ')

        # register application
        cl_id, cl_sc = Mastodon.create_app(
            self.config['app']['name'], api_base_url=inst)

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
            'cf. Keys and tokens can be get from https://developer.twitter.com/'
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

    def __init__(self):
        # files
        twoot_dir = os.path.expanduser('~/.' + __file__)
        if not os.path.isdir(twoot_dir):
            os.mkdir(twoot_dir)
        self.config_file = twoot_dir + '/config.json'
        self.data_file = twoot_dir + '/data.json'

        # config
        self.max_texts = 20

        if os.path.isfile(self.config_file):
            self.setup = False

            # load config
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

        else:
            self.setup = True

            # initialize
            print('Welcome to Twoot! Please answer a few questions.')
            self.config = {}

            # ask for config entries
            self.__app_questions()
            self.mastodon = self.__mastodon_questions()
            self.twitter = self.__twitter_questions()

            print('\nAll configuration done. Thanks!')

            # save config
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=4, sort_keys=True)

        # utility
        self.html2text = html2text.HTML2Text()
        self.html2text.body_width = 0

        # fetch self account information
        self.ms_account = self.mastodon.account_verify_credentials()
        self.tw_account = self.twitter.account.verify_credentials()

    def __pre_process(self, text):
        # no endline spaces
        text = re.sub(r'\s+\n', r'\n', text)

        # expand links
        links = [w for w in text.split() if urlparse(w.strip()).scheme]

        for l in links:
            r = requests.head(l)
            url = r.headers.get('location', l)
            text = text.replace(l, url)

        return text

    def __toot(self, text):
        text = self.__pre_process(text)

        if not text in self.data['texts']:
            r = self.mastodon.toot(text)
            self.__store_text(text)
            Twoot.logger.info('Created a toot (id: {})'.format(r['id']))

    def __tweet(self, text):
        text = self.__pre_process(text)

        if not text in self.data['texts']:
            # TODO: just switch this after getting consumer keys
            print('tweet:', text)
            #r = self.twitter.status.update(status=text)
            self.__store_text(text)
            #Twoot.logger.info('Created a tweet (id: {})'.format(r['id']))

    def __store_text(self, text):
        self.data['texts'].append(text)
        if len(self.data['texts']) > self.max_texts:
            self.data['texts'].pop(-1)

    def __html2text(self, html):
        # basically, trust html2text
        text = self.html2text.handle(html).strip()

        # treat links and hashtags
        text = re.sub(r'\[#(.*?)\]\(.*?\)', r'#\1', text)
        text = re.sub(r'\[.*?\]\((.*?)\)', r'\1', text)

        return text

    def get_new_toots(self):
        # who am I?
        me = self.ms_account['id']

        # fetch toots
        last_id = self.data.get('ms_last', False)
        if last_id:
            r = self.mastodon.account_statuses(
                me, exclude_replies=True, since_id=last_id)
        else:
            r = self.mastodon.account_statuses(me, exclude_replies=True)

        # update last toot ID
        if len(r) > 0:
            self.data['ms_last'] = r[0]['id']

        if last_id:
            return r
        else:
            return []

    def get_new_tweets(self):
        # who am I?
        me = self.tw_account['screen_name']

        # fetch toots
        last_id = self.data.get('tw_last', False)
        if last_id:
            r = self.twitter.statuses.user_timeline(
                screen_name=me, exclude_replies=True, since_id=last_id, tweet_mode="extended")
        else:
            r = self.twitter.statuses.user_timeline(
                screen_name=me, exclude_replies=True, tweet_mode="extended")

        # update last tweet ID
        if len(r) > 0:
            self.data['tw_last'] = r[0]['id']

        if last_id:
            return r
        else:
            return []

    def tweets2toots(self, tweets):
        for t in reversed(tweets):
            if t.get('full_text', False):
                self.__toot(t['full_text'])
            else:
                self.__toot(t['text'])

    def toots2tweets(self, toots):
        for t in reversed(toots):
            self.__tweet(self.__html2text(t.content))

    def run(self):
        Twoot.logger.info('Running')

        # initialize data
        if os.path.isfile(self.data_file):
            with open(self.data_file) as f:
                self.data = json.loads(f.read(), 'utf-8')
        else:
            self.data = {'texts': []}

        # tweets -> toots
        toots = self.get_new_toots()
        if not self.setup:
            self.toots2tweets(toots)

        # toots -> tweets
        tweets = self.get_new_tweets()
        if not self.setup:
            self.tweets2toots(tweets)

        # save data
        with codecs.open(self.data_file, 'w', 'utf-8') as f:
            json.dump(
                self.data, f, indent=4, sort_keys=True, ensure_ascii=False)


if __name__ == '__main__':
    main()
