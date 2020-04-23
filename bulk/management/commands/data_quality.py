import os
import csv
import json
import datetime
import tempfile
import zipfile
import uuid
import boto3
import base62
from django.core.management.base import BaseCommand
from django.db.models import F, Count, Avg
from openstates_metadata import STATES_BY_NAME
from openstates.data.models import (
    LegislativeSession,
    Bill,
    BillAbstract,
    BillAction,
    BillTitle,
    BillIdentifier,
    RelatedBill,
    BillSponsorship,
    BillDocument,
    BillVersion,
    BillDocumentLink,
    BillVersionLink,
    BillSource,
    VoteEvent,
    PersonVote,
    VoteCount,
    VoteSource,
)
from utils.common import abbr_to_jid
from utils.orgs import get_chambers_from_abbr
from collections import defaultdict
from statistics import mean

# Loads the global bill array with all bills from given state and session to use
#   when creating the json
def load_bills(state, session):
    sobj = LegislativeSession.objects.get(
        jurisdiction_id=abbr_to_jid(state), identifier=session
    )
    bills = Bill.objects.filter(legislative_session=sobj).prefetch_related("actions", "sponsorships", "votes", "votes__counts", "sources")
    return bills


def get_available_sessions(state):
    return sorted(
        s.identifier
        for s in LegislativeSession.objects.filter(jurisdiction_id=abbr_to_jid(state))
    )

def total_bills_per_session(bills, chambers):
    total_bills_per_session = defaultdict(list)
    for chamber in chambers:
        chamber_name = chamber.name.lower()
        total_bills = bills.filter(from_organization=chamber).count()
        # Set variables to empty strings in case any info is blank
        latest_bill_created_id = ""
        latest_bill_created_date = ""
        bill_with_latest_action_id = ""
        latest_action_date = ""
        latest_action_description = ""

        bill_with_earliest_action_id = ""
        earliest_action_date = ""
        earliest_action_description = ""

        if total_bills > 0:
            latest_bill = bills.filter(from_organization=chamber).latest("created_at")
            latest_bill_created_id = latest_bill.identifier
            latest_bill_created_date = latest_bill.created_at.strftime("%Y-%m-%d")
            bill_with_latest_action = bills.filter(from_organization=chamber).latest("actions__date")
            # In case bills don't have actions
            if bill_with_latest_action.actions.count() > 0:
                bill_with_latest_action_id = bill_with_latest_action.identifier
                latest_action = bill_with_latest_action.actions.latest("date")
                latest_action_date = latest_action.date
                latest_action_description = latest_action.description

            # Earliest Action
            bill_with_earliest_action = bills.filter(from_organization=chamber).earliest("actions__date")
            # In case bills don't have actions
            if bill_with_earliest_action.actions.count() > 0:
                bill_with_earliest_action_id = bill_with_earliest_action.identifier
                earliest_action = bill_with_earliest_action.actions.earliest("date")
                earliest_action_date = earliest_action.date
                earliest_action_description = earliest_action.description

        total_bills_per_session[chamber_name].append({
            "chamber": chamber_name,
            "total_bills": total_bills,
            "latest_bill_created_id": latest_bill_created_id,
            "latest_bill_created_date": latest_bill_created_date,
            "bill_id_with_latest_action": bill_with_latest_action_id,
            "latest_action_date": latest_action_date,
            "latest_action_description": latest_action_description,
            "bill_id_with_earliest_action": bill_with_earliest_action_id,
            "earliest_action_date": earliest_action_date,
            "earliest_action_description": earliest_action_description}
        )
    return total_bills_per_session


def average_number_data(bills, chambers):
    average_num_data = defaultdict(list)

    for chamber in chambers:
        chamber_name = chamber.name.lower()
        total_sponsorships_per_bill = []
        total_actions_per_bill = []
        total_votes_per_bill = []

        average_sponsors_per_bill = 0
        average_actions_per_bill = 0
        average_votes_per_bill = 0

        for bill in bills.filter(from_organization=chamber):
            total_sponsorships_per_bill.append(bill.sponsorships.count())
            total_actions_per_bill.append(bill.actions.count())
            total_votes_per_bill.append(bill.votes.count())

        average_sponsors_per_bill = round(mean(total_sponsorships_per_bill))
        average_actions_per_bill = round(mean(total_actions_per_bill))
        average_votes_per_bill = round(mean(total_votes_per_bill))

        average_num_data[chamber_name].append({
            "chamber": chamber_name,
            "average_sponsors_per_bill": average_sponsors_per_bill,
            "average_actions_per_bill": average_actions_per_bill,
            "average_votes_per_bill": average_votes_per_bill}
        )
    return average_num_data


def no_sources(bills, chambers):
    no_sources_data = defaultdict(list)
    for chamber in chambers:
        chamber_name = chamber.name.lower()
        total_bills_no_sources = bills.filter(from_organization=chamber, sources=None).count()
        total_votes_no_sources = bills.filter(from_organization=chamber, votes__sources=None).count()
        no_sources_data[chamber_name].append({
            "chamber": chamber_name,
            "total_bills_no_sources": total_bills_no_sources,
            "total_votes_no_sources": total_votes_no_sources}
        )
    return no_sources_data


def bill_subjects(bills, chambers):
    bill_subjects_data = defaultdict(list)
    for chamber in chambers:
        chamber_name = chamber.name.lower()
        overall_number_of_subjects = bills.distinct("subject").values_list("subject", flat=True).count()
        number_of_subjects = bills.filter(from_organization=chamber).distinct("subject").values_list("subject", flat=True).count()
        number_of_bills_without_subjects = bills.filter(from_organization=chamber, subject=None).count()
        bill_subjects_data[chamber_name].append({
            "chamber": chamber_name,
            "overall_number_of_subjects": overall_number_of_subjects,
            "number_of_subjects": number_of_subjects,
            "number_of_bills_without_subjects": number_of_bills_without_subjects}
        )
    return bill_subjects_data

def write_json_to_file(filename, data):
    with open(filename, "w") as file:
        file.write(data)

# Example command
# docker-compose run --rm django poetry run ./manage.py data_quality Virginia
class Command(BaseCommand):
    help = "export data quality as a json"

    def add_arguments(self, parser):
        parser.add_argument("state")
        # parser.add_argument("sessions", nargs="*")
        # parser.add_argument("--all-sessions", action="store_true")


    def handle(self, *args, **options):
        state = options["state"]
        sessions = get_available_sessions(state)
        chambers = get_chambers_from_abbr(state)
        for session in sessions:
            # Resets bills inbetween every session
            bills = load_bills(state, session)
            if bills.count() > 0:
                bills_per_session_data = total_bills_per_session(bills, chambers)
                average_num_data = average_number_data(bills, chambers)
                no_sources_data = no_sources(bills, chambers)
                bill_subjects_data = bill_subjects(bills, chambers)

                overall_json_data = json.dumps({
                    "bills_per_session_data": dict(bills_per_session_data),
                    "average_num_data": dict(average_num_data),
                    "no_sources_data": dict(no_sources_data),
                    "bill_subjects_data": dict(bill_subjects_data)
                })
                filename = f"{state}_{session}_data_quality.json"
                write_json_to_file(filename, overall_json_data)