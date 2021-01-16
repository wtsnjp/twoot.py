from setuptools import setup

setup(
    name='twoot.py',
    version='1.3.0',
    description='Sync Twitter and Mastodon nicely',
    license='MIT License',
    author='Takuto ASAKURA (wtsnjp)',
    author_email='wtsnjp@gmail.com',
    install_requires=[
        'docopt', 'Mastodon.py', 'twitter', 'html2text', 'requests'
    ],
    url='https://github.com/wtsnjp/twoot.py')
