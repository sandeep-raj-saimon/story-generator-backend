from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone

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
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.email

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
    is_current = models.BooleanField(default=True)
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