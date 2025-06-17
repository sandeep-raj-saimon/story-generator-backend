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
    Middleware to handle credit deduction for story saving and media generation.
    Deducts 1 credit when a story is saved.
    Deducts credits for image/audio generation based on CREDIT_COSTS.
    """
    
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is a story save endpoint

        # Handle media generation endpoints (image/audio)
        if request.method == 'POST' and any(endpoint in request.path_info for endpoint in ['generate-image', 'generate-audio', 'generate-bulk-image', 'generate-bulk-audio']):
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
                    # Determine media type and credit cost
                    media_type = None
                    if 'image' in request.path_info:
                        media_type = 'image'
                    elif 'audio' in request.path_info:
                        media_type = 'audio'
                    
                    if not media_type:
                        return self.get_response(request)

                    # Calculate credit cost
                    credit_cost = 0
                    if 'bulk' in request.path_info:
                        # For bulk generation, we need to calculate total cost for all scenes
                        # Extract story_id from path
                        path_parts = request.path_info.split('/')
                        story_id = None
                        for i, part in enumerate(path_parts):
                            if part == 'stories' and i + 1 < len(path_parts):
                                story_id = path_parts[i + 1]
                                break
                        
                        if story_id:
                            # Get all scenes for the story
                            scenes = Scene.objects.filter(story_id=story_id, is_active=True)
                            if media_type == 'image':
                                credit_cost = sum([math.ceil(CREDIT_COSTS['image']) for _ in scenes])
                            elif media_type == 'audio':
                                credit_cost = sum([math.ceil(CREDIT_COSTS['audio'] * len(scene.content)) for scene in scenes])
                    else:
                        # For single scene generation
                        # Extract scene_id from path
                        path_parts = request.path_info.split('/')
                        scene_id = None
                        for i, part in enumerate(path_parts):
                            if part == 'scenes' and i + 1 < len(path_parts):
                                scene_id = path_parts[i + 1]
                                break
                        
                        if scene_id:
                            scene = Scene.objects.filter(id=scene_id).first()
                            if scene:
                                if media_type == 'image':
                                    credit_cost = math.ceil(CREDIT_COSTS['image'])
                                elif media_type == 'audio':
                                    credit_cost = math.ceil(CREDIT_COSTS['audio'] * len(scene.content))

                    if credit_cost > 0:
                        print(f"Credit cost: {credit_cost}")
                        with transaction.atomic():
                            # Get user's active credits
                            user_credits = Credits.objects.select_for_update().get(user_id=user_id, is_active=True)
                            
                            # Check if user has enough credits
                            if user_credits.credits_remaining < credit_cost:
                                response = Response(
                                    {'error': f'Insufficient credits for {media_type} generation. Required: {credit_cost}, Available: {user_credits.credits_remaining}'},
                                    status=status.HTTP_402_PAYMENT_REQUIRED
                                )
                                response.accepted_renderer = JSONRenderer()
                                response.accepted_media_type = "application/json"
                                response.renderer_context = {}
                                response.render()
                                return response

                            # Deduct credits
                            user_credits.credits_remaining -= credit_cost
                            user_credits.save()

                            # Create credit transaction record
                            if 'bulk' in request.path_info:
                                # For bulk generation, create one transaction for the total cost
                                CreditTransaction.objects.create(
                                    user_id=user_id,
                                    credits_used=credit_cost,
                                    transaction_type='debit'
                                )
                            else:
                                # For single scene generation
                                scene_id = None
                                path_parts = request.path_info.split('/')
                                for i, part in enumerate(path_parts):
                                    if part == 'scenes' and i + 1 < len(path_parts):
                                        scene_id = path_parts[i + 1]
                                        break
                                
                                scene = Scene.objects.filter(id=scene_id).first() if scene_id else None
                                CreditTransaction.objects.create(
                                    user_id=user_id,
                                    scene=scene,
                                    credits_used=credit_cost,
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