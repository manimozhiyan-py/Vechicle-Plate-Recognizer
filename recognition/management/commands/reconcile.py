"""Reconcile stuck captures - re-queue captures that fell through the cracks."""
import logging

from django.core.management.base import BaseCommand
from django.db import models
from django.utils import timezone
from datetime import timedelta

from recognition.models import Capture
from recognition.tasks import enqueue

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find stuck captures (pending/unqueued or processing too long) and re-queue them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--stuck-minutes",
            type=int,
            default=5,
            help="Consider processing stuck after this many minutes (default: 5)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Max captures to process (default: 100)",
        )

    def handle(self, *args, **options):
        stuck_minutes = options["stuck_minutes"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        now = timezone.now()
        stuck_threshold = now - timedelta(minutes=stuck_minutes)

        # Find stuck captures:
        # 1. PENDING but never queued (queued_at is null)
        # 2. PROCESSING but locked_at is older than threshold (worker died)
        stuck = Capture.objects.filter(
            models.Q(status=Capture.Status.PENDING, queued_at__isnull=True) |
            models.Q(status=Capture.Status.PROCESSING, locked_at__lt=stuck_threshold)
        ).order_by("locked_at", "created_at")[:limit]

        count = 0
        for cap in stuck:
            if cap.status == Capture.Status.PROCESSING:
                self.stdout.write(
                    f"  {cap.uuid}: PROCESSING since {cap.locked_at} "
                    f"({(now - cap.locked_at).total_seconds():.0f}s ago) - resetting to PENDING"
                )
                if not dry_run:
                    cap.status = Capture.Status.PENDING
                    cap.locked_at = None
                    cap.save(update_fields=["status", "locked_at"])
            else:
                self.stdout.write(
                    f"  {cap.uuid}: PENDING, queued_at={cap.queued_at} - re-queueing"
                )

            if not dry_run:
                enqueue(cap.uuid)
                self.stdout.write(f"    → enqueued")
            count += 1

        if count == 0:
            self.stdout.write(self.style.SUCCESS("No stuck captures found"))
        else:
            action = "Would re-queue" if dry_run else "Re-queued"
            self.stdout.write(self.style.SUCCESS(f"{action} {count} stuck capture(s)"))