"""Canonical account identifiers shared by control and container processes."""
import re

def valid_slug(value):
    return isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9-]{0,31}',value,flags=re.ASCII) is not None and not value.endswith('-')

def valid_owner(value):
    return isinstance(value,str) and value==value.upper() and valid_slug(value.lower())

def owner_for(slug):
    if not valid_slug(slug):raise ValueError('invalid_account_id')
    return slug.upper()
