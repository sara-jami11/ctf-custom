#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Seed fake CTF data for local/demo use.

Creates a complete demo dataset: challenges with flags/hints/solutions,
brackets, teams, users (with captains), solves, fails, awards, ratings,
reviews and tracking events.

Usage (inside the CTFd container, after /setup has been completed):

    python scripts/fake_data.py                 # seed an empty instance
    python scripts/fake_data.py --force         # wipe non-admin data first
    python scripts/fake_data.py --teams 15 --users 75 --challenges 25

Requirements: the `Faker` package (part of the dev dependency group):
    pip install Faker==4.1.0

Notes:
    * All generated users and teams use the password "password".
    * The flag of every challenge equals the challenge name.
    * Assigns a bracket to every user and team (this CTFd fork requires
      a bracket selection before /challenges can be accessed).
    * No challenge files are created (files would not exist on disk).
"""

import argparse
import datetime
import os
import random
import sys

# Allow running as `python scripts/fake_data.py` from the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faker import Faker

from CTFd import create_app
from CTFd.cache import clear_challenges, clear_config, clear_pages, clear_standings
from CTFd.models import (
    Awards,
    Brackets,
    Challenges,
    Fails,
    Flags,
    Hints,
    Ratings,
    Solves,
    Solutions,
    Teams,
    Tracking,
    Users,
)
from CTFd.utils import config as cfg

fake = Faker()

CATEGORIES = [
    "Exploitation",
    "Reversing",
    "Web",
    "Forensics",
    "Scripting",
    "Cryptography",
    "Networking",
]
COMPANIES = ["Corp", "Inc.", "Squad", "Team"]
ICONS = [None, "shield", "bug", "crown", "crosshairs", "ban", "lightning", "code"]


class Seeder:
    def __init__(self, db):
        self.db = db
        self.buf = []

    def add(self, row, batch=200):
        self.db.session.add(row)
        self.buf.append(row)
        if len(self.buf) >= batch:
            self.db.session.commit()
            self.buf.clear()

    def flush(self):
        if self.buf:
            self.db.session.commit()
            self.buf.clear()


def wipe_non_admin_data(db):
    """Remove all non-admin generated data (keeps admins and config)."""
    from CTFd.models import ChallengeFiles, UserFieldEntries, TeamFieldEntries

    print("WIPING non-admin data", flush=True)
    for model in (
        Ratings,
        Awards,
        Fails,
        Solves,
        Tracking,
        UserFieldEntries,
        TeamFieldEntries,
        Flags,
        Hints,
        Solutions,
        ChallengeFiles,
        Challenges,
    ):
        model.query.delete()
    for u in Users.query.filter(Users.type != "admin").all():
        db.session.delete(u)
    for t in Teams.query.all():
        db.session.delete(t)
    for b in Brackets.query.all():
        db.session.delete(b)
    db.session.commit()
    clear_standings()
    clear_challenges()
    print("wipe done", flush=True)


def seed(args):
    app = create_app()
    with app.app_context():
        db = app.db

        if cfg.is_setup() is False:
            print("ERROR: CTFd is not set up yet. Complete /setup first.", flush=True)
            sys.exit(1)

        existing = Teams.query.count() + Challenges.query.count()
        if existing:
            if not args.force:
                print(
                    "ERROR: data already exists (teams=%d challenges=%d). "
                    "Use --force to wipe non-admin data first."
                    % (Teams.query.count(), Challenges.query.count()),
                    flush=True,
                )
                sys.exit(1)
            wipe_non_admin_data(db)

        s = Seeder(db)
        now = datetime.datetime.utcnow()

        # ---- CHALLENGES with flags ----
        print("GENERATING %d CHALLENGES" % args.challenges, flush=True)
        used_words = set()
        for _ in range(args.challenges):
            word = fake.word()
            while word in used_words:
                word = fake.word()
            used_words.add(word)
            chal = Challenges(
                name=word,
                description=fake.paragraph(),
                attribution="Written by %s" % fake.name(),
                value=random.choice(range(100, 500, 50)),
                category=random.choice(CATEGORIES),
            )
            s.add(chal)
            s.flush()
            s.add(Flags(challenge_id=chal.id, content=word, type="static"))

        # ---- SOLUTIONS ----
        print("GENERATING SOLUTIONS", flush=True)
        for chal in Challenges.query.all():
            s.add(
                Solutions(
                    content=" ".join(fake.paragraph() for _ in range(3)),
                    state="visible",
                    challenge_id=chal.id,
                )
            )

        # ---- HINTS (0-3 per challenge, weighted) ----
        print("GENERATING HINTS", flush=True)
        for chal in Challenges.query.all():
            for _ in range(random.choices([0, 1, 2, 3], weights=[20, 30, 35, 15])[0]):
                s.add(
                    Hints(
                        title=fake.sentence(),
                        content=fake.paragraph(),
                        cost=random.choice([0, 50, 100]),
                        challenge_id=chal.id,
                        type="standard",
                    )
                )
        s.flush()

        # ---- BRACKETS ----
        print("GENERATING BRACKETS", flush=True)
        for btype in ("teams", "users"):
            for _ in range(args.brackets):
                s.add(
                    Brackets(
                        name="%s%d"
                        % (fake.word().capitalize(), random.randint(1, 1000)),
                        description=fake.sentence(),
                        type=btype,
                    )
                )
        s.flush()
        team_brackets = [b.id for b in Brackets.query.filter_by(type="teams").all()]
        user_brackets = [b.id for b in Brackets.query.filter_by(type="users").all()]

        # ---- TEAMS ----
        print("GENERATING %d TEAMS" % args.teams, flush=True)
        used_names = set()
        for _ in range(args.teams):
            name = "%s%d" % (fake.word().capitalize(), random.randint(1, 1000))
            while name in used_names:
                name = "%s%d" % (fake.word().capitalize(), random.randint(1, 1000))
            used_names.add(name)
            team = Teams(name=name, password="password")
            # every team gets a bracket (required by this fork)
            team.bracket_id = random.choice(team_brackets)
            if random.random() > 0.5:
                team.affiliation = "%s %s" % (
                    fake.word().title(),
                    random.choice(COMPANIES),
                )
            s.add(team)
        s.flush()

        # ---- USERS (round-robin so no team is empty) ----
        print("GENERATING %d USERS" % args.users, flush=True)
        team_ids = [t.id for t in Teams.query.order_by(Teams.id).all()]
        used_names = set()
        used_emails = set()
        order = team_ids[:]
        random.shuffle(order)
        created = 0
        attempts = 0
        while created < args.users and attempts < args.users * 50:
            attempts += 1
            name = fake.first_name()
            email = fake.email()
            if name in used_names or email in used_emails:
                continue
            used_names.add(name)
            used_emails.add(email)
            user = Users(name=name, email=email, password="password")
            user.verified = True
            user.team_id = order[created % len(order)]
            # every user gets a bracket (required by this fork)
            user.bracket_id = random.choice(user_brackets)
            if random.random() > 0.5:
                user.affiliation = "%s %s" % (
                    fake.word().title(),
                    random.choice(COMPANIES),
                )
            s.add(user)
            try:
                s.flush()
            except Exception:
                s.db.session.rollback()
                used_emails.discard(email)
                continue
            s.add(Tracking(ip=fake.ipv4(), user_id=user.id))
            created += 1
            if created % 25 == 0:
                s.flush()
                print("  users created: %d" % created, flush=True)
        s.flush()
        print("total users: %d" % Users.query.count(), flush=True)

        # ---- CAPTAINS (lowest-id member of each team) ----
        print("ASSIGNING CAPTAINS", flush=True)
        for t in Teams.query.all():
            members = sorted(m.id for m in t.members)
            if members:
                t.captain_id = members[0]
        s.flush()

        # ---- CHALLENGE-OPEN TRACKING EVENTS ----
        print("GENERATING TRACKING EVENTS", flush=True)
        chal_ids = [c.id for c in Challenges.query.all()]
        base_time = now - datetime.timedelta(days=14)
        for u in Users.query.filter_by(type="user").all():
            if u.team_id is None:
                continue
            t = base_time + datetime.timedelta(minutes=random.randint(0, 12000))
            opened = random.sample(
                chal_ids, random.randint(int(len(chal_ids) * 0.6), len(chal_ids))
            )
            for ch in opened:
                s.add(
                    Tracking(
                        type="challenges.open",
                        ip=fake.ipv4(),
                        target=ch,
                        user_id=u.id,
                        date=t,
                    )
                )
                t += datetime.timedelta(minutes=random.randint(1, 30))

        # ---- SOLVES (every team gets several) ----
        print("GENERATING SOLVES", flush=True)
        for t in Teams.query.all():
            members = [m.id for m in t.members]
            if not members:
                continue
            when = now - datetime.timedelta(days=7)
            for ch in random.sample(chal_ids, random.randint(4, len(chal_ids))):
                when += datetime.timedelta(minutes=random.randint(2, 90))
                s.add(
                    Solves(
                        user_id=random.choice(members),
                        team_id=t.id,
                        challenge_id=ch,
                        ip="127.0.0.1",
                        provided="flag",
                        date=when,
                    )
                )

        # ---- AWARDS ----
        print("GENERATING AWARDS", flush=True)
        for u in Users.query.filter_by(type="user").all():
            if u.team_id is None:
                continue
            when = now - datetime.timedelta(days=7)
            for _ in range(random.randint(1, 5)):
                when += datetime.timedelta(minutes=random.randint(2, 90))
                s.add(
                    Awards(
                        user_id=u.id,
                        team_id=u.team_id,
                        name=fake.word(),
                        value=random.randint(-10, 10),
                        icon=random.choice(ICONS),
                        date=when,
                    )
                )

        # ---- WRONG FLAGS ----
        print("GENERATING WRONG FLAGS", flush=True)
        for u in Users.query.filter_by(type="user").all():
            if u.team_id is None:
                continue
            when = now - datetime.timedelta(days=7)
            for _ in range(random.randint(3, 30)):
                when += datetime.timedelta(minutes=random.randint(1, 20))
                s.add(
                    Fails(
                        user_id=u.id,
                        team_id=u.team_id,
                        challenge_id=random.choice(chal_ids),
                        ip="127.0.0.1",
                        provided=fake.word(),
                        date=when,
                    )
                )

        # ---- RATINGS & REVIEWS ----
        print("GENERATING RATINGS", flush=True)
        for solve in Solves.query.all():
            if random.random() < 0.6:
                s.add(
                    Ratings(
                        user_id=solve.user_id,
                        challenge_id=solve.challenge_id,
                        value=random.choice((-1, 1)),
                        review=fake.sentence() if random.random() < 0.7 else None,
                        date=(solve.date or now)
                        + datetime.timedelta(minutes=random.randint(5, 120)),
                    )
                )
        s.flush()

        clear_config()
        clear_standings()
        clear_challenges()
        clear_pages()

        print("", flush=True)
        print(
            "DONE: users=%d teams=%d challenges=%d solves=%d fails=%d awards=%d ratings=%d"
            % (
                Users.query.count(),
                Teams.query.count(),
                Challenges.query.count(),
                Solves.query.count(),
                Fails.query.count(),
                Awards.query.count(),
                Ratings.query.count(),
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed fake CTF data")
    parser.add_argument("--teams", type=int, default=15)
    parser.add_argument("--users", type=int, default=75)
    parser.add_argument("--challenges", type=int, default=25)
    parser.add_argument("--brackets", type=int, default=5)
    parser.add_argument(
        "--force",
        action="store_true",
        help="wipe all non-admin users/teams/challenges/etc before seeding",
    )
    seed(parser.parse_args())
