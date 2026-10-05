"""Purge image files for captures past their retention period."""
import time
import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from recognition.models import Capture

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Purge image files for captures past their retention period"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be deleted without actually deleting",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of captures to process per batch (default: 100)",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously with interval",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=3600,
            help="Seconds to sleep between loops (default: 3600)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        loop = options["loop"]
        interval = options["interval"]

        if dry_run:
            self.stdout.write("DRY RUN - no files will be deleted")

        def process_batch():
            now = timezone.now()
            captures = Capture.objects.filter(
                purge_after__lt=now,
                image_purged_at__isnull=True,
            ).exclude(image="").order_by("purge_after")[:batch_size]

            count = 0
            for capture in captures:
                if dry_run:
                    self.stdout.write(f"Would purge: {capture.uuid} (outcome={capture.outcome}, purge_after={capture.purge_after})")
                else:
                    # Delete original image
                    if capture.image:
                        capture.image.delete(save=False)
                    # Delete processed image
                    if capture.processed_image:
                        capture.processed_image.delete(save=False)
                    # Mark as purged
                    capture.image_purged_at = timezone.now()
                    capture.save(update_fields=["image_purged_at"])
                    self.stdout.write(f"Purged: {capture.uuid}")
                count += 1
            return count

        if loop:
            self.stdout.write(f"Running in loop mode (interval={interval}s)...")
            while True:
                processed = process_batch()
                if processed == 0:
                    self.stdout.write("No captures to purge, sleeping...")
                time.sleep(interval)
        else:
            processed = process_batch()
            self.stdout.write(f"Done. Processed {processed} capture(s).")