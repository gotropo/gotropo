import json
from botocore.vendored import requests

def lambda_handler(
        event,
        context,
        create_function,
        delete_function,
        update_function,
        test_function ):

    funcs = dict(
        Create = create_function,
        Delete = delete_function,
        Update = update_function,
        Test = test_function
    )

    rt = event.get("RequestType",None)
    if rt:
        f = funcs.get(rt, None)
        if f:
            call_func(f, event, context)
        else:
            print("RequestType unknown")
    else:
        print("RequestType not found")

def call_func(function, event, context):
    success = "SUCCESS"
    failure = "FAILED"
    responseData = dict()
    try:
        (successful, responseData) = function(event, context)
        if successful:
            responseStatus = success
        else:
            responseStatus = failure
    except Exception as e:
        print("Exception calling event function:")
        print(e)
        responseStatus = failure
    finally:
        send_response(event, context, responseStatus, responseData)

def test_request(event, context, responseStatus, responseData):
    class response(object):
        status_code = 200

    print("Testing response section")
    r = response()
    return r

def send_response(event, context, responseStatus, responseData):
    responseBody = {'Status': responseStatus,
                    'Reason': 'See the details in CloudWatch Log Stream: ' + context.log_stream_name,
                    'PhysicalResourceId': responseData.pop('PhysicalResourceId',context.log_stream_name),
                    'StackId': event['StackId'],
                    'RequestId': event['RequestId'],
                    'LogicalResourceId': event['LogicalResourceId'],
                    'Data': responseData}
    print('RESPONSE BODY:\n' + json.dumps(responseBody))
    try:
        if (event['ResponseURL'] == "Test"):
            req = test_request(event, context, responseStatus, responseData)
        else:
            req = requests.put(event['ResponseURL'], data=json.dumps(responseBody))
        if req.status_code != 200:
            print(req.text)
            raise Exception('Recieved non 200 response while sending response to CFN.')
        return
    except requests.exceptions.RequestException as e:
        print(req.text)
        print(e)
        raise
