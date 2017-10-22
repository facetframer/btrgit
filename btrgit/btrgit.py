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

    volumes_parser = parsers.add_parser('volumes', help='Show the subvolumes ')
    volumes_parser.add_argument('path', type=str)

    log_parser = parsers.add_parser('log', help='Show changes made to a directory tree or files')
    log_parser.add_argument('path', type=str, help='Path to operate on', nargs='?', default='.')
    log_parser.add_argument('commit', nargs='?', help='Show what changed in this snapshot (regular expression)', type=str)
    log_parser.add_argument('--no-files', action='store_true', help='Do not show files that have changed (just snapshots)')
    show_mx = log_parser.add_mutually_exclusive_group()
    show_mx.add_argument('--all', action='store_true', help='Show all changes before')
    show_mx.add_argument('--single', action='store_true', help='Show just this change')

    copy_parser = parsers.add_parser('copy', help='Copy a file or directory at a particular commit')
    copy_parser.add_argument('path', type=str, help='Path to operate on')
    copy_parser.add_argument('commit', type=int, help='Show what changed in this snapshot (regular expression)')
    copy_parser.add_argument('target_path', type=str, help='Path to copy to', nargs='?')


    return parser

Snapshot = collections.namedtuple('Snapshot', 'path transaction old_transaction commit creation_time')

def get_subvolumes(mount):
    LOGGER.debug('Getting subvolumes for mount: %r', mount)
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

    # snapper snapshots only
    # /home/.snapshots/2146/snapshot
    snapshots = [os.path.join(mount, snapshot) for snapshot in snapshots]

    old_transactions = transactions[1:] + ['0']
    commits = [s.split('/')[-2] for s in snapshots]
    commits = [int(c) if c.isdigit() else None for c in commits]
    creation_times = map(get_creation_time, snapshots)
    info =  zip(snapshots, transactions, old_transactions, commits, creation_times)
    snapshots = list(itertools.starmap(Snapshot, info))
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
    args.path = os.path.abspath(args.path)

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    path_list = args.path.split('/')

    if args.command == 'log':
        mount = find_mount(mount_points(), args.path)
        LOGGER.debug('%r is under mount: %r', args.path, mount)
        subvolumes = [x for x in get_subvolumes(mount) if x.commit]


        if args.commit:
            subvolumes = [x for x in subvolumes if re.search(args.commit, x.path)]

            if not subvolumes:
                raise Exception('No such subvolumes')
            elif len(subvolumes) != 1:
                raise Exception('Matches multiple commits')

        for subvolume in subvolumes:
            LOGGER.debug('Considering volume %r', subvolume)
            changed_files = find_changed_files(mount, subvolume)
            for filename in changed_files:
                LOGGER.debug('Considering file %r', filename)
                if is_subpath(args.path, filename):
                    LOGGER.debug('Match! %r %r', args.path, filename)
                    if args.no_files:
                        print subvolume.creation_time, subvolume.commit, subvolume.path
                        break

                    else:
                        print subvolume.creation_time, subvolume.commit, subvolume.path, filename
                        sys.stdout.flush()

    elif args.command == 'copy':
        mount = find_mount(mount_points(), args.path)
        subvolume, = [s for s in get_subvolumes(mount) if s.commit == args.commit]
        source_path = os.path.join(subvolume.path, os.path.relpath(args.path, mount))

        if args.target_path in (None, '-'):
            if not os.path.isfile(source_path):
                raise Exception('Can only stream regular files')
            with open(source_path) as stream:
                for line in stream:
                    print line
        else:
            subprocess.check_call(['cp','-rp','--preserve', source_path, args.target_path])


    elif args.command == 'volumes':
        mount = find_mount(mount_points(), args.path)
        for volume in get_subvolumes(mount):
            print volume.path, volume.transaction, volume.old_transaction, volume.commit
    else:
        raise ValueError(args.command)



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
    command = ['btrfs', 'subvolume', 'find-new', subvolume.path, subvolume.old_transaction]
    changes = subprocess.check_output(command)
    LOGGER.debug('Running %r', ' '.join(command))

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

    LOGGER.debug('%r files changed in subvolume %r', len(files), subvolume)

    return files

if __name__ == '__main__':
    main()
