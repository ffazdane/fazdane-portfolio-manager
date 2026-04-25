import os
from dotenv import load_dotenv
load_dotenv()

from src.market.tastytrade_client import get_tastytrade_session, get_accounts

session, err = get_tastytrade_session()
print('Session:', session is not None, err)
if session:
    accounts, err2 = get_accounts(session)
    print('Accounts:', accounts)
    print('Error:', err2)
