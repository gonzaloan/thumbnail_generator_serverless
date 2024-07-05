import json
import boto3
from datetime import datetime
from io import BytesIO
from PIL import Image, ImageOps
import os
import uuid

s3 = boto3.client('s3')
size = int(os.environ.get('THUMBNAIL_SIZE', 128))  # Default size if not set
dbtable = str(os.environ.get('DYNAMODB_TABLE', 'thumbnail'))
dynamodb = boto3.resource('dynamodb',
                            region_name=os.environ.get('REGION_NAME', 'us-east-1'))
def s3_thumbnail_generator(event, context):

    print("EVENT:::", event)
    try:
        bucket = event['Records'][0]['s3']['bucket']['name']
        key = event['Records'][0]['s3']['object']['key']
        img_size = event['Records'][0]['s3']['object']['size']
    except KeyError as e:
        print(f"Error parsing event: {e}")
        return {"statusCode": 400, "body": json.dumps("Invalid event format")}

    print("BUCKET:::", bucket)

    if not key.endswith("_thumbnail.png"):
        try:
            image = get_s3_image(bucket, key)
            thumbnail = image_to_thumbnail(image)
            thumbnail_key = new_filename(key)

            url = upload_to_s3(bucket, thumbnail_key, thumbnail, img_size)
            return {"statusCode": 200, "body": json.dumps({"url": url})}
        except Exception as e:
            print(f"Error processing image: {e}")
            return {"statusCode": 500, "body": json.dumps("Internal server error")}
    
    return {"statusCode": 200, "body": json.dumps("No thumbnail created")}

def get_s3_image(bucket, key):
    response = s3.get_object(Bucket=bucket, Key=key)
    image_content = response['Body'].read()
    file = BytesIO(image_content)
    img = Image.open(file)
    return img

def image_to_thumbnail(img):
    return ImageOps.fit(img, (size, size), Image.LANCZOS)

def new_filename(key):
    key_split = key.rsplit('.', 1)
    return key_split[0] + "_thumbnail.png"

def upload_to_s3(bucket, key, image, img_size):
    out_thumbnail = BytesIO()
    image.save(out_thumbnail, format='PNG')
    out_thumbnail.seek(0)

    response = s3.put_object(
        Bucket=bucket, 
        Key=key, 
        Body=out_thumbnail, 
        ContentType='image/png'
    )
    
    print(response)

    url = f"https://{bucket}.s3.amazonaws.com/{key}"

    s3_save_thumbnail_url_to_dynamo(url, img_size)
    return url


def s3_save_thumbnail_url_to_dynamo(url_path, img_size):
    toint = float(img_size*0.53)/1000
    table = dynamodb.Table(dbtable)
    response = table.put_item(
        Item={
            'id': str(uuid.uuid4()),
            'url': str(url_path),
            'approxReducedSize': str(toint) + str(' KB'),
            'createdAt': str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            'updatedAt': str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }
    )

    return {"statusCode": 200, "body": json.dumps(response)}

def s3_get_thumbnail(event, context):
    table = dynamodb.Table(dbtable)
    response = table.get_item(Key={'id': event['pathParameters']['id']})
    item = response.get('Item', {})
    return {"statusCode": 200, "body": json.dumps(item),
            "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
            "isBase64Encoded": False}

def s3_delete_thumbnail(event, context):
    item_id = event['pathParameters']['id']
    table = dynamodb.Table(dbtable)
    try:
        response = table.delete_item(Key={'id': item_id})
        print(response)
        if response['ResponseMetadata']['HTTPStatusCode'] == 200:
            return {"statusCode": 200, "body": json.dumps("Thumbnail deleted successfully")}
         
        return {"statusCode": 500, "body": json.dumps("Internal server error")}
    except KeyError as e:
        print(f"Error parsing event: {e}")
        return {"statusCode": 400, "body": json.dumps("Invalid event format")}

    
def s3_get_thumbnails_urls(event, context):
    table = dynamodb.Table(dbtable)
    response = table.scan()
    data = response['Items']

    while 'LastEvaluatedKey' in response:
        response = table.scan(ExclusiveStartKey=response['LastEvaluatedKey'])
        data.extend(response['Items'])

    return {"statusCode": 200, "body": json.dumps(data)}

