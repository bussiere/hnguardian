import socket
import sys
import re
from pymongo import MongoClient
from threading import Thread
from time import sleep
import requests

SERVER = 'irc.freenode.com'
CHANNEL = '#hackernews'
BOT_NICK = 'hnguardian'
db = MongoClient().hnguardian
irc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

def action(text):
    irc.send(b('PRIVMSG ' + CHANNEL + ' :\x01ACTION ' + text + '\x01\r\n'))

def pm(to, text):
    irc.send(b('PRIVMSG ' + to + ' :' + ' '.join(text.split()) + ' \r\n'))

def share_show(last_show):
    show = requests.get(
        'https://hn.algolia.com/api/v1/search_by_date',
        params={'tags': 'show_hn', 'hitsPerPage': 1}
    )
    
    if show.status_code == 200:
        show = show.json()['hits'][0]

        if show['created_at'] != last_show:
            action('[@' + show['author'] + '] ' + show['title'])
            action('https://news.ycombinator.com/item?id=' + show['objectID'])

    sleep(5)
    share_show(show['created_at'])

def b(string):
    return bytes(string, 'utf-8')

def link(sender, args):
    person = db.people.find_one({'nick': sender.lower()})

    if not person:
        db.people.update(
            {'nick': sender.lower()},
            {'$set': {'infolink': args[0]}},
            True
        )
        pm('nickserv', 'info ' + sender)

    elif not person['registered']:
        pm(sender, '''Your Freenode nick must be registered before
                   linking your Hacker News account or others could
                   spoof it.''')

    else:
        pm(sender, 'Add the string "irc:' + args[0] + ''':irc" to
                   your HN bio. If our system sees it in 30 seconds
                   your Hacker News account will be linked to your
                   Freenode nick! (You can delete it after).''')
        sleep(30)
        r = requests.get('https://news.ycombinator.com/user?id=' + args[0])
        bio_nick = re.search('irc:(.+):irc', r.text)
        
        if bio_nick:
            bio_nick = bio_nick.group(1).lower()

            if bio_nick == sender.lower():
                db.people.update(
                    {'nick': sender},
                    {'$set': {'username': args[0]}},
                    True
                )
                pm(sender, 'Link successful!')
                pm(sender, '''People can get your Hacker News username by
                           entering this command in #hackernews:''')
                pm(sender, 'username <Freenode nick>')

            else:
                pm(sender, 'Link not successful :(')

        else:
            pm(sender, 'Could not find string in bio.')

irc.connect((SERVER, 6667))
irc.send(b('USER ' + ' '.join(BOT_NICK) + ' :beep boop\n'))
irc.send(b('NICK ' + BOT_NICK + '\n'))
irc.send(b('JOIN ' + CHANNEL + '\n'))
Thread(target=share_show, args=['']).start()

while 1:
    text = irc.recv(2040).decode('utf-8').split('\n')

    for line in text:
        words = line.split()
        if len(words) < 2:
            break

        if words[0] == 'PING':
            irc.send(b('PONG ' + line[1] + '\r\n'))

        elif words[1] == 'JOIN':
            nick = re.search(':(.+)!', words[0]).group(1).lower()
            person = db.people.find_one({'nick': nick})

            if not person or not person['username']:
                pm('nickserv', 'info ' + nick)
                # We'll receive a PM from nickserv letting us know if the nick
                # is registered. This code is below.

        elif words[1] == 'PRIVMSG' or words[1] == 'NOTICE':
            sender = re.search(':(.+?)(!|$)', words[0]).group(1)
            to = words[2]
            command = words[3][1:]
            args = words[4:]

            if sender == 'NickServ' and command == 'Information':
                # We asked NickServ about a nick that isn't in our db yet. The
                # nick is registered so we can ask them to link their HN
                # account.
                nick = re.search('\x02(.+)\x02', args[1]).group(1)
                person = db.people.find_one({'nick': nick})

                db.people.update(
                    {'nick': nick},
                    {'$set':
                        {'nick': nick, 'registered': True, 'infolink': False}
                    },
                    True
                )

                if person and person['infolink']:
                    link(nick, [person['infolink']])

                else:
                    pm(nick, '''Welcome to #hackernews! Our database doesn't
                             recognize your nickname. Enter this command to
                             link your Hacker News account to your Freenode
                             nick so others can recognize you:''')
                    pm(nick, '/msg hnguardian link <HN username>')

            elif sender == 'NickServ' and ''.join(args) == 'isnotregistered.':
                nick = re.search('\x02(.+)\x02', command).group(1)
                person = db.people.find_one({'nick': nick})

                if person and person['infolink']:
                    pm(nick, '''Your Freenode nick must be registered before
                             linking your Hacker News account or others could
                             spoof it.''')

            elif command == 'link' and to == BOT_NICK and len(args) == 1:
                link(sender, args)

            elif command == 'username' and to == CHANNEL and len(args) == 1:
                name = db.people.find_one({'username': args[0]})

                if name:
                    pm(CHANNEL, args[0] + "'s Hacker News username is "
                                + name['username'])

                else:
                    pm(CHANNEL, args[0] + """ hasn't linked their Hacker News
                                username to their Freenode nick yet:""")
                    pm(CHANNEL, '/msg hnguardian link <HN username>')
