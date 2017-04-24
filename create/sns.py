from troposphere import sns
from troposphere import Output

def topic(template, name, subscriptions):
    subs = [sns.Subscription(Endpoint = s[1], Protocol = "SMS") for s in subscriptions]
    sns_topic = template.add_resource(sns.Topic(
        name,
        DisplayName = name,
        Subscription = subs,
    ))
    return sns_topic
