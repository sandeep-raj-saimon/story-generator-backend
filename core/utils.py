import boto3
import json
import traceback
from django.conf import settings
import redis
import os

CREDIT_COSTS = {
        'image': 10,  # 10 credits per image
        'audio': 0.25,  # 0.25 credits per audio
    }

def redis_client():
    return redis.Redis(
        host=os.getenv('REDISHOST'),
        port=os.getenv('REDISPORT'),
        password=os.getenv('REDISPASSWORD')
    )
def send_job_to_sqs(job, request_data, media_id=None):
    """
    Send a job to AWS SQS queue and update the job with the message ID.
    
    Args:
        job (Job): The job instance to send
        request_data (dict): The data to send in the SQS message
        
    Returns:
        Job: The updated job instance with message_id
        
    Raises:
        Exception: If there's an error sending to SQS
    """
    try:
        # Initialize SQS client
        job_id = job.id
        request_data['job_id'] = str(job_id)
        request_data['media_id'] = media_id
        sqs_client = boto3.client(
            'sqs',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )

        # Send message to SQS
        print('request_data', request_data)
        response = sqs_client.send_message(
            QueueUrl=settings.WHISPR_TALES_QUEUE_URL,
            MessageBody=json.dumps(request_data)
        )
        print(f'job sent to the sqs {request_data} for job Id: {job_id}')
        # Update job with message ID
        job.message_id = response['MessageId']
        job.save()
        return job

    except Exception as e:
        error_traceback = traceback.format_exc()
        print(f'Error sending job to SQS:')
        print(f'Error: {str(e)}')
        print('Traceback:')
        print(error_traceback)
        # Mark job as failed
        job.mark_as_failed(f"Failed to send to SQS: {str(e)}\nTraceback:\n{error_traceback}")
        raise

def create_redis_lock(scene_id, media_type):
    """
    Create a Redis lock for media generation.
    
    Args:
        scene_id (str): The ID of the scene
        media_type (str): The type of media being generated ('image' or 'audio')
        
    Returns:
        bool: True if lock was created, False if lock already exists
    """
    try:
        # Create Redis lock key
        lock_key = f"scene_{scene_id}_{media_type}_lock"
        
        # Check if lock exists
        if redis_client().exists(lock_key):
            return False
            
        # Set lock with 5 minute expiry
        redis_client.setex(lock_key, 300, 'locked')
        return True
        
    except Exception as e:
        print(f"Error creating Redis lock: {str(e)}")
        return False
