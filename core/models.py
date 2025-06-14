from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
import uuid
from datetime import timedelta

class User(AbstractUser):
    """Custom user model with additional fields"""
    email = models.EmailField(_('email address'), unique=True)
    bio = models.TextField(_('bio'), blank=True)
    profile_picture = models.URLField(
        _('profile picture'),
        max_length=1000,  # S3 URLs can be quite long
        blank=True,
        null=True,
        help_text='S3 URL for the profile picture'
    )
    referral_code = models.CharField(
        _('referral code'),
        max_length=50,
        blank=True,
        null=True,
        help_text='Unique referral code for this user'
    )
    referred_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='referrals',
        help_text='User who referred this user'
    )
    language = models.CharField(
        _('language'),
        max_length=50,
        blank=True,
        null=True,
        default='en-US',
        help_text='Language of the user'
    )
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email

    # def save(self, *args, **kwargs):
    #     # Generate referral code if not set
    #     if not self.referral_code:
    #         self.referral_code = str(uuid.uuid4())[:8].upper()
    #     super().save(*args, **kwargs)

class Story(models.Model):
    """Story model to store user's stories"""
    title = models.CharField(_('title'), max_length=200)
    content = models.TextField(_('content'))
    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='stories',
        verbose_name=_('author')
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    is_public = models.BooleanField(_('is public'), default=False)
    word_count = models.IntegerField(_('word count'), default=0)
    is_active = models.BooleanField(_('is active'), default=True)
    is_default = models.BooleanField(_('is_default'), default=False)
    is_public = models.BooleanField(_('is_public'), default=False)
    language = models.CharField(
        _('language'),
        max_length=50,
        blank=True,
        null=True,
        default='en-US',
        help_text='Language of the story')
    class Meta:
        verbose_name = _('story')
        verbose_name_plural = _('stories')
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Calculate word count before saving
        self.word_count = len(self.content.split())
        super().save(*args, **kwargs)

class Scene(models.Model):
    """Scene model for story segments"""
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='scenes',
        verbose_name=_('story')
    )
    title = models.CharField(_('title'), max_length=200)
    content = models.TextField(_('content'))
    order = models.PositiveIntegerField(_('order'), default=0)
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    emotion = models.JSONField(default=list, null=True, blank=True)
    is_active = models.BooleanField(_('is active'), default=True)
    scene_description = models.TextField(
        _('scene description'),
        help_text=_('AI-generated scene description'),
        blank=True
    )

    class Meta:
        verbose_name = _('scene')
        verbose_name_plural = _('scenes')
        ordering = ['order']

    def __str__(self):
        return f"{self.story.title} - Scene {self.order}: {self.title}"

class Media(models.Model):
    """Media model for story-related images and audio"""
    MEDIA_TYPE_CHOICES = [
        ('image', _('Image')),
        ('audio', _('Audio')),
    ]
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='media',
        verbose_name=_('story')
    )
    scene = models.ForeignKey(
        Scene,
        on_delete=models.CASCADE,
        related_name='media',
        verbose_name=_('scene')
    )
    media_type = models.CharField(
        _('media type'),
        max_length=10,
        choices=MEDIA_TYPE_CHOICES
    )
    url = models.URLField(
        _('S3 URL'),
        max_length=1000,
        help_text=_('S3 URL for the media file')
    )
    description = models.TextField(
        _('description'),
        help_text=_('AI-generated media description'),
        blank=True
    )
    request_id = models.CharField(
        _('request id'),
        max_length=200,
        null=True,
        blank=True
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    is_active = models.BooleanField(_('is active'), default=True)
    class Meta:
        verbose_name = _('media')
        verbose_name_plural = _('media')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_media_type_display()} for {self.scene.title}"

class Revision(models.Model):
    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('mp4', 'MP4'),
        ('audio', 'Audio'),
    ]
    
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='revisions')
    format = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    sub_format = models.CharField(max_length=50, null=True, blank=True)
    url = models.URLField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.story.title} - {self.format} ({self.created_at})"

class Credits(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='credits',
        verbose_name=_('user')
    )
    credits_remaining = models.IntegerField(
        _('credits remaining'),
        default=300,
        help_text=_('Number of credits remaining for the user')
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)
    is_active = models.BooleanField(_('is active'), default=True)

    class Meta:
        verbose_name = _('credit')
        verbose_name_plural = _('credits')
        ordering = ['-updated_at']

    def __str__(self):
        return f"{self.user.username} - {self.credits_remaining} credits"


class CreditTransaction(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='credit_transactions',
        verbose_name=_('user')
    )
    scene = models.ForeignKey(
        'Scene',
        on_delete=models.SET_NULL,
        null=True,
        related_name='credit_transactions',
        verbose_name=_('scene')
    )
    credits_used = models.PositiveIntegerField(
        _('credits used'),
        help_text=_('Number of credits used in this transaction')
    )
    transaction_type = models.CharField(
        _('transaction type'),
        max_length=20,
        choices=[
            ('debit', 'Debit'),
            ('credit', 'Credit'),
        ],
        default='debit'
    )
    created_at = models.DateTimeField(_('created at'), auto_now_add=True)
    updated_at = models.DateTimeField(_('updated at'), auto_now=True)

    class Meta:
        verbose_name = _('credit transaction')
        verbose_name_plural = _('credit transactions')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.credits_used} credits ({self.transaction_type})"

class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    order_id = models.CharField(max_length=200)
    metadata = models.JSONField(null=True, blank=True)
    def __str__(self):
        return f"{self.user.username} - {self.plan.name} - {self.amount}"
    
class Payment(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    payment_id = models.CharField(max_length=200)
    payment_status = models.CharField(max_length=20)
    payment_signature = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.order.user.username} - {self.order.amount}"

class Job(models.Model):
    """
    Model to track AWS SQS jobs for reliability and monitoring.
    """
    JOB_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ]

    JOB_TYPE_CHOICES = [
        ('generate_media', 'Generate Media'),
        ('generate_pdf_preview', 'Generate PDF Preview'),
        ('generate_audio_preview', 'Generate Audio Preview'),
        ('generate_video_preview', 'Generate Video Preview'),
        ('generate_entire_audio', 'Generate Entire Audio')
    ]

    # Job identification
    message_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="AWS SQS Message ID")
    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=JOB_STATUS_CHOICES, default='pending')
    
    # Related objects
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='jobs')
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    scene = models.ForeignKey(Scene, on_delete=models.CASCADE, related_name='jobs', null=True, blank=True)
    
    # Job details
    request_data = models.JSONField(help_text="Original request data sent to SQS")
    response_data = models.JSONField(null=True, blank=True, help_text="Response data from the job")
    error_message = models.TextField(null=True, blank=True, help_text="Error message if job failed")
    
    # Credit information
    credit_cost = models.PositiveIntegerField(
        default=0,
        help_text="Number of credits required for this job"
    )
    credit_transaction = models.ForeignKey(
        CreditTransaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='jobs',
        help_text="Associated credit transaction for this job"
    )
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Retry information
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['job_type']),
            models.Index(fields=['created_at']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"{self.job_type} - {self.id} ({self.status})"

    def mark_as_processing(self):
        """Mark job as processing and set start time."""
        self.status = 'processing'
        self.started_at = timezone.now()
        self.save()

    def mark_as_completed(self, response_data=None):
        """Mark job as completed and set completion time."""
        self.status = 'completed'
        self.completed_at = timezone.now()
        if response_data:
            self.response_data = response_data
        self.save()

    def mark_as_failed(self, error_message):
        """Mark job as failed and store error message."""
        self.status = 'failed'
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.save()

    def schedule_retry(self):
        """Schedule a retry for failed jobs."""
        if self.retry_count < self.max_retries:
            self.retry_count += 1
            # Exponential backoff: 5min, 15min, 45min
            delay_minutes = 5 * (3 ** (self.retry_count - 1))
            self.next_retry_at = timezone.now() + timedelta(minutes=delay_minutes)
            self.status = 'pending'
            self.save()
            return True
        return False

    def cancel(self):
        """Cancel the job."""
        self.status = 'cancelled'
        self.completed_at = timezone.now()
        self.save()