from django.db import transaction
from rest_framework.response import Response
from rest_framework import status
from .models import Credits, CreditTransaction, Scene
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from django.conf import settings
from jwt import decode as jwt_decode
from jwt.exceptions import InvalidTokenError
from .utils import *
import math
import redis
import os
from rest_framework.renderers import JSONRenderer

User = get_user_model()

redis_client = redis.Redis(
    host=os.getenv('REDISHOST'),
    port=os.getenv('REDISPORT'),
    password=os.getenv('REDISPASSWORD')
)

class CreditDeductionMiddleware:
    """
    Middleware to handle credit deduction for story saving.
    Deducts 1 credit when a story is saved.
    """
    
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is a story save endpoint
        if request.method == 'POST' and 'stories' in request.path_info and not any(endpoint in request.path_info for endpoint in ['generate', 'segment', 'scenes']):
            try:
                # Get the JWT token from the Authorization header
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if not auth_header.startswith('Bearer '):
                    response = Response(
                        {'error': 'Invalid authorization header'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                    response.accepted_renderer = JSONRenderer()
                    response.accepted_media_type = "application/json"
                    response.renderer_context = {}
                    response.render()
                    return response

                # Extract and decode the JWT token
                token = auth_header.split(' ')[1]
                decoded_token = jwt_decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                user_id = decoded_token.get('user_id')

                if user_id:
                    with transaction.atomic():
                        # Get user's active credits
                        user_credits = Credits.objects.select_for_update().get(user_id=user_id, is_active=True)
                        
                        # Check if user has enough credits
                        if user_credits.credits_remaining < 1:
                            response = Response(
                                {'error': 'Insufficient credits to save story'},
                                status=status.HTTP_402_PAYMENT_REQUIRED
                            )
                            response.accepted_renderer = JSONRenderer()
                            response.accepted_media_type = "application/json"
                            response.renderer_context = {}
                            response.render()
                            return response

                        # Deduct 1 credit
                        user_credits.credits_remaining -= 1
                        user_credits.save()

                        # Create credit transaction record
                        CreditTransaction.objects.create(
                            user_id=user_id,
                            credits_used=1,
                            transaction_type='debit'
                        )

            except Exception as e:
                response = Response(
                    {'error': str(e)},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                response.accepted_renderer = JSONRenderer()
                response.accepted_media_type = "application/json"
                response.renderer_context = {}
                response.render()
                return response

        # For media generation endpoints, only handle Redis locking (no credit deduction)
        if request.method == 'POST':
            path = request.path_info
            if any(endpoint in path for endpoint in ['generate-image', 'generate-audio', 'generate-bulk-image', 'generate-bulk-audio']):
                # Get the media type and scene ID for locking
                media_type = 'image' if 'image' in path else 'audio'
                scene_id = request.path.split('/')[-3]
                
                # Create Redis lock key
                lock_key = f"scene_{scene_id}_{media_type}_lock"
                
                # Check if lock exists
                if redis_client.exists(lock_key):
                    response = Response(
                        {'error': 'A media generation request is already in progress for this scene. Please try again later.', 'error_code': 'E001' },
                        status=status.HTTP_403_FORBIDDEN
                    )
                    response.accepted_renderer = JSONRenderer()
                    response.accepted_media_type = "application/json"
                    response.renderer_context = {}
                    response.render()
                    return response

                # Set lock with 5 minute expiry
                redis_client.setex(lock_key, 300, 'locked')

        return self.get_response(request)