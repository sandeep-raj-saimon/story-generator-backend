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
    Middleware to handle credit deduction for media generation.
    Deducts credits based on the media type and number of scenes.
    """
    
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only process POST requests for media generation endpoints
        if not request.method == 'POST':
            return self.get_response(request)
        
        # Check if this is a media generation endpoint
        path = request.path_info
        if not any(endpoint in path for endpoint in ['generate-image', 'generate-audio', 'generate-bulk-image', 'generate-bulk-audio']):
            return self.get_response(request)
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

        try:
            # Extract and decode the JWT token
            token = auth_header.split(' ')[1]
            decoded_token = jwt_decode(token, settings.SECRET_KEY, algorithms=['HS256'])
            user_id = decoded_token.get('user_id')
            
            if not user_id:
                return Response(
                    {'error': 'Invalid token'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            # Get the user
            try:
                user = User.objects.get(id=user_id)
                request.user = user
            except User.DoesNotExist:
                response = Response(
                    {'error': 'User not found', 'error_code': 'E002'},
                    status=status.HTTP_401_UNAUTHORIZED
                )
                response.accepted_renderer = JSONRenderer()
                response.accepted_media_type = "application/json"
                response.renderer_context = {}
                response.render()
                return response

        except InvalidTokenError:
            response = Response(
                {'error': 'Invalid token', 'error_code': 'E003'},
                status=status.HTTP_401_UNAUTHORIZED
            )
            response.accepted_renderer = JSONRenderer()
            response.accepted_media_type = "application/json"
            response.renderer_context = {}
            response.render()
            return response

        # Get the media type from the URL
        media_type = 'image' if 'image' in path else 'audio'
        
        # For single scene generation, we are not using bulk generation
        scene_count = 1
        # http://127.0.0.1:8000/api/stories/3/scenes/19/generate-image/ or http://127.0.0.1:8000/api/stories/3/scenes/19/generate-audio/
        scene_id = request.path.split('/')[-3]
        scene = Scene.objects.get(id=int(scene_id))
        if scene.story.author != request.user:
            return Response(
                {'error': 'You are not authorized to generate media for this scene', 'error_code': 'E004' },
                status=status.HTTP_403_FORBIDDEN
            )

        # Calculate total credits needed
        credits_needed = 0
        if media_type == 'image':
            # credits_needed = self.CREDIT_COSTS[media_type] * scene_count
            credits_needed = math.ceil(CREDIT_COSTS[media_type] * scene_count)
        else:
            # credits_needed = self.CREDIT_COSTS[media_type] * len(scene.content)
            credits_needed = math.ceil(CREDIT_COSTS[media_type] * len(scene.content))
        try:
            with transaction.atomic():
                # Get user's active credits
                print('getting started', request.user)
                credits = Credits.objects.select_for_update().filter(
                    user=request.user,
                    is_active=True
                ).first()
                print('credits', credits)
                if not credits:
                    print('No active credit account found', request.user)
                    return Response(
                        {'error': 'No active credit account found'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Check if user has enough credits
                if credits.credits_remaining < credits_needed:
                    print('Insufficient credits', request.user, credits.credits_remaining, credits_needed)
                    return Response(
                        {
                            'error': f'Insufficient credits. You need {credits_needed} credits for this operation.',
                            'credits_remaining': credits.credits_remaining,
                            'error_code': 'E005'
                        },
                        status=status.HTTP_402_PAYMENT_REQUIRED
                    )
                print('Credits remaining', credits.credits_remaining, credits_needed)
                # Deduct credits
                credits.credits_remaining -= credits_needed
                credits.save()
                print('Credits deducted', request.user, credits.credits_remaining, credits_needed)
                # Create credit transaction record
                CreditTransaction.objects.create(
                    user=request.user,
                    credits_used=credits_needed,
                    transaction_type='debit',
                    scene=Scene.objects.get(id=int(scene_id))
                )
                print('Credit transaction created', request.user, credits.credits_remaining, credits_needed)
                # Add credits info to request for use in views
                request.credits_info = {
                    'credits_deducted': credits_needed,
                    'credits_remaining': credits.credits_remaining
                }

                return self.get_response(request)

        except Exception as e:
            print('Error processing credits', e)
            return Response(
                {'error': f'Error processing credits: {str(e)}', 'error_code': 'E006'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )