import boto3
import json
import traceback
from django.conf import settings

CREDIT_COSTS = {
        'image': 100,  # 1 credit per image
        'audio': 0.3,  # 2 credits per audio
    }

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