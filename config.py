import os
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

def get_wc_api_keys(site_name):
    """
    Fetch the consumer key and secret for a site.
    """
    consumer_key = os.getenv(f'WC_{site_name.upper()}_CONSUMER_KEY')
    consumer_secret = os.getenv(f'WC_{site_name.upper()}_CONSUMER_SECRET')
    
    if not consumer_key or not consumer_secret:
        raise ValueError(f"API keys for site '{site_name}' are not set in the .env file.")
    
    return consumer_key, consumer_secret

# Example sites
SITES = [
    {
        'name': 'S1',
        'url': 'https://www.cbdoilking.co.uk',
        'consumer_key': get_wc_api_keys('site1')[0],
        'consumer_secret': get_wc_api_keys('site1')[1],
    },
    {
        'name': 'S2',
        'url': 'https://www.thcvapepens.co.uk',
        'consumer_key': get_wc_api_keys('site2')[0],
        'consumer_secret': get_wc_api_keys('site2')[1],
    },
    {
        'name': 'S3',
        'url': 'https://www.thcvapepen.co.uk',
        'consumer_key': get_wc_api_keys('site3')[0],
        'consumer_secret': get_wc_api_keys('site3')[1],
    },
    {
        'name': 'S4',
        'url': 'https://www.weedpens.co.uk',
        'consumer_key': get_wc_api_keys('site4')[0],
        'consumer_secret': get_wc_api_keys('site4')[1],
    },
    {
        'name': 'S5',
        'url': 'https://www.cannabispen.co.uk',
        'consumer_key': get_wc_api_keys('site5')[0],
        'consumer_secret': get_wc_api_keys('site5')[1],
    }
]
