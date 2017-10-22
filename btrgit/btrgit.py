#!/usr/bin/python

import argparse
import collections
import itertools
import logging
import os
import os.path
import pipes
import re
import subprocess
import sys

import dateutil.parser

LOGGER = logging.getLogger()

def build_parser():
    parser = argparse.ArgumentParser(prog='btrgit', description='An interface to btrfs that behaves like git')
    parser.add_argument('--debug', action='store_true', help='Print debug output')
    parsers = parser.add_subparsers(dest='command')

    log_parser = parsers.add_parser('log', help='Show changes made to a file')
    log_parser.add_argument('path', type=str, help='Path to operate on')
    log_parser.add_argument('commit', nargs='?', help='Show what changed in this snapshot (regular expression)', type=str)
    log_parser.add_argument('--no-files', action='store_true', help='Do not show files that have changed (just snapshots)')

    show_mx = log_parser.add_mutually_exclusive_group()
    show_mx.add_argument('--all', action='store_true', help='Show all changes before')
    show_mx.add_argument('--single', action='store_true', help='Show just this change')
    return parser

Snapshot = collections.namedtuple('Snapshot', 'snapshot transaction old_transaction')

def get_subvolumes(mount):
    string = subprocess.check_output(
        "btrfs subvolume list {} | cut -d ' ' -f 4,9".format(pipes.quote(mount)),
        shell=True)
    transactions = []
    snapshots = []
    for l in string.splitlines():
        transaction, snapshot = l.split()
        snapshots.append(snapshot)
        transactions.append(transaction)

    pairs = zip(snapshots, transactions)
    pairs.sort(key=lambda x: -int(x[1]))
    snapshots = [p[0] for p in pairs]
    transactions = [p[1] for p in pairs]

    snapshots = [os.path.join(mount, snapshot) for snapshot in snapshots]

    old_transactions = transactions[1:] + ['0']
    info =  zip(snapshots, transactions, old_transactions)
    snapshots = itertools.starmap(Snapshot, info)
    return snapshots

def mount_points():
    with open('/proc/mounts') as stream:
         return [x for x in [x.split()[1] for x in stream.read().splitlines()] if x.startswith('/')]

def find_mount(mount_points, path):
    path = os.path.abspath(path)
    best_mount = ''
    path = path.rstrip('/')
    for mount in mount_points:
        mount = mount.rstrip('/')
        mount_list = mount.split('/')
        if os.path.commonprefix([mount, path]) == mount:
            if len(mount) > len(best_mount):
                best_mount = mount


    if best_mount == '':
        raise Exception('Could not find mount')
    else:
        return best_mount

def main():
    LOGGER.debug('Starting')
    args = build_parser().parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    path_list = args.path.split('/')

    mount = find_mount(mount_points(), args.path)
    LOGGER.debug('%r is under mount: %r', args.path, mount)

    subvolumes = get_subvolumes(mount)

    if args.commit:
        subvolumes = [x for x in subvolumes if re.search(args.commit, x.snapshot)]

        if not subvolumes:
            raise Exception('No such subvolumes')
        elif len(subvolumes) != 1:
            raise Exception('Matches multiple commits')

    for subvolume in subvolumes:
        creation_time = get_creation_time(subvolume.snapshot)
        LOGGER.debug('Getting changed files for %r', subvolume)
        changed_files = find_changed_files(mount, subvolume)
        for filename in changed_files:
            if args.no_files:
                print creation_time, subvolume.snapshot
                break
            else:
                if is_subpath(args.path, filename):
                    print creation_time, subvolume.snapshot, filename
                    sys.stdout.flush()

def is_subpath(prefix, path):
    prefix = prefix.rstrip('/')
    path = path.rstrip('/')
    return os.path.commonprefix([prefix, path]) == prefix

def get_creation_time(snapshot):
    data = subprocess.check_output(['btrfs', 'subvolume', 'show', snapshot])
    for line in data.splitlines():
        line = line.strip()
        if line.startswith('Creation time'):
            date_string = line.split(':', 1)[1].strip()
            return dateutil.parser.parse(date_string, fuzzy=True).isoformat()
    else:
        raise Exception('Could not find creation time')



def find_changed_files(mount, subvolume):
    changes = subprocess.check_output(['btrfs', 'subvolume', 'find-new', subvolume.snapshot, subvolume.old_transaction])
    files = []

    for index, line in enumerate(changes.splitlines()):
        if not line.strip():
            continue
        if line == '#':
            continue
        if line.startswith('transid marker was'):
            continue

        try:
            filename = line.split()[16]
        except:
            print index, repr(line)
            raise

        filename = os.path.join(mount, filename)

        if filename.strip():
            files.append(filename)

    return files

if __name__ == '__main__':
    main()
