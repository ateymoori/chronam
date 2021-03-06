from __future__ import absolute_import, print_function

import json
from urllib import urlopen

from chronam.core.models import Batch

from . import LoggingCommand


class Command(LoggingCommand):
    help = "compares batches loaded with the public site"  # NOQA: A003

    def handle(self, *args, **options):
        url = 'https://chroniclingamerica.loc.gov/batches.json'
        missing_batches = []
        missing_pages = []
        while url:
            batch_info = json.loads(urlopen(url).read())
            for batch in batch_info['batches']:
                self.stdout.write("comparing %(name)s with %(page_count)s pages" % batch)
                try:
                    my_batch = Batch.objects.get(name=batch['name'])
                    if my_batch.page_count != batch['page_count']:
                        batch['my_page_count'] = my_batch.page_count
                        missing_pages.append(batch)
                except Batch.DoesNotExist:
                    missing_batches.append(batch)
            url = batch_info.get('next', None)

        if len(missing_batches) > 0:
            self.stdout.write("missing batches:")
            for batch in missing_batches:
                self.stdout.write("  %s" % batch['name'])
            self.stdout.write()

        if len(missing_pages) > 0:
            self.stdout.write("batches that are missing pages:")
            for batch in missing_pages:
                self.stdout.write(
                    "  %s has %s instead of %s pages"
                    % (batch['name'], batch['my_page_count'], batch['page_count'])
                )
            self.stdout.write()
