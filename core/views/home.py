import datetime

from django.conf import settings
from django.core import urlresolvers
from django.core.cache import cache
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.template.response import TemplateResponse

from chronam.core import forms
from chronam.core.decorator import add_cache_headers
from chronam.core.models import Ethnicity, Issue, Language, Page, Place, Title


def home(request, date=None):
    context = {"crumbs": list(settings.BASE_CRUMBS)}
    today = datetime.date.today()
    context["date"] = date = today.replace(year=today.year - 100)
    context["pages"] = _frontpages(request, date)
    return TemplateResponse(request, "home.html", context)


def _frontpages(request, date):
    # if there aren't any issues default to the first 20 which
    # is useful for testing the homepage when there are no issues
    # for a given date
    issues = Issue.objects.filter(date_issued=date).prefetch_related("title", "batch")
    if issues.count() == 0:
        issues = Issue.objects.all()[0:20]

    # Prefetch the page count to avoid O(n) queries during serialization:
    issues = issues.annotate(page_count=Count("pages"))

    # To avoid URL generation triggering O(n) queries looking up the first page
    # and it's issue/batch info, we'll do one subselect to collect lal of the
    # results in the first pass:
    issues = issues.extra(
        select={
            "first_page_pk": """
                SELECT id FROM core_page
                    WHERE issue_id = core_issue.id AND jp2_filename IS NOT NULL
                    ORDER BY sequence ASC
                LIMIT 1
            """
        }
    )

    first_pages = {
        page.issue_id: page for page in Page.objects.filter(pk__in=[issue.first_page_pk for issue in issues])
    }

    results = []
    for issue in issues:
        first_page = first_pages.get(issue.pk)
        if not first_page:
            continue

        # Rather than lookup the issue on-access we'll replace it with the same
        # data we already have:
        first_page.issue = issue

        path_parts = {
            "lccn": issue.title.lccn,
            "date": issue.date_issued,
            "edition": issue.edition,
            "sequence": first_page.sequence,
        }
        url = urlresolvers.reverse("chronam_page", kwargs=path_parts)

        issue_info = {
            "label": "%s" % issue.title.display_name,
            "url": url,
            "place_of_publication": issue.title.place_of_publication,
            "pages": issue.page_count,
            "thumbnail_url": first_page.thumb_url,
            "medium_url": first_page.medium_url,
        }

        if first_page.iiif_client:
            issue_info["iiif_thumbnail_base_url"] = first_page.iiif_base_url

        results.append(issue_info)

    return results


def frontpages(request, date):
    _year, _month, _day = date.split("-")

    try:
        date = datetime.date(int(_year), int(_month), int(_day))
    except ValueError:
        raise Http404

    results = _frontpages(request, date)

    return JsonResponse(results, safe=False)


@add_cache_headers(settings.METADATA_TTL_SECONDS, settings.SHARED_CACHE_MAXAGE_SECONDS)
def tabs(request, date=None):
    params = request.GET if request.GET else None
    form = forms.SearchPagesForm(params)
    adv_form = forms.AdvSearchPagesForm(params)

    context = {"search_form": form, "adv_search_form": adv_form}
    context.update(get_newspaper_info())
    return TemplateResponse(request, "includes/tabs.html", context)


def get_newspaper_info():
    info = cache.get("newspaper_info")
    if info is None:
        titles_with_issues = Title.objects.filter(has_issues=True)
        titles_with_issues_count = titles_with_issues.count()

        _places = Place.objects.filter(titles__in=titles_with_issues)
        states_with_issues = sorted({place.state for place in _places if place.state is not None})

        _languages = Language.objects.filter(titles__in=titles_with_issues)
        languages_with_issues = sorted({(lang.code, lang.name) for lang in _languages})

        ethnicities_with_issues = []
        for e in Ethnicity.objects.all():
            # filter out a few ethnicities:
            # https://rdc.lctl.gov/trac/chronam/ticket/724#comment:22
            if e.has_issues and e.name not in ["African", "Canadian", "Welsh"]:
                ethnicities_with_issues.append(e.name)

        info = {
            "titles_with_issues_count": titles_with_issues_count,
            "states_with_issues": states_with_issues,
            "languages_with_issues": languages_with_issues,
            "ethnicities_with_issues": ethnicities_with_issues,
        }

        cache.set("newspaper_info", info, settings.METADATA_TTL_SECONDS)

    return info
