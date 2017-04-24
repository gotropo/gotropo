#log the event to cloudwatch for debugging
from os import environ

def handler(event, context):
    print('event')
    print(event)
    print('context')
    print(context)
    print("environment")
    print("\n".join([str((k,v)) for k,v in environ.items()]))
    return 'Event Complete'
