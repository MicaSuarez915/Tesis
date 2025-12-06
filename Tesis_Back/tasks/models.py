from django.db import models
from django.utils import timezone
import uuid

class Task(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('canceled', 'Canceled'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ]
    
    id = models.CharField(max_length=50, primary_key=True, editable=False)
    causa = models.ForeignKey(
        'causa.Causa',  
        on_delete=models.CASCADE,
        related_name='tasks',
        default=-1  # -1 para tasks generales
    )
    content = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )
    deadline_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    order = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['order', '-created_at']
    
    def save(self, *args, **kwargs):
        if not self.id:
            # Generar ID único tipo "t_1244efj34234b"
            self.id = f"t_{uuid.uuid4().hex[:12]}"
            
        # Auto-completar completed_at cuando status cambia a 'done'
        if self.status == 'done' and not self.completed_at:
            self.completed_at = timezone.now()
        elif self.status != 'done':
            self.completed_at = None
            
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Task {self.id}: {self.content[:50]}"