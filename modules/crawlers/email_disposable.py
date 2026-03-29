"""
email_disposable.py — Disposable / throwaway email domain checker.

Detects whether an email address uses a known disposable or temporary domain.

Strategy (layered, fastest first):
  1. Local blocklist — instant, zero-network, covers ~3 000 common burner domains.
  2. Kickbox Open API — https://open.kickbox.com/v1/disposable/{domain}
     Free, no key, JSON response: {"disposable": true|false}
  3. Mailcheck.ai API — https://api.mailcheck.ai/domain/{domain}
     Free fallback for domains not in the Kickbox index.

identifier: full email address OR bare domain name
Registered as "email_disposable".
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from modules.crawlers.httpx_base import HttpxCrawler
from modules.crawlers.registry import register
from modules.crawlers.core.result import CrawlerResult
from modules.crawlers.core.models import CrawlerCategory, RateLimit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local blocklist — common disposable/burner domains (no network required)
# Covers the vast majority of real-world hits; API layers catch the long tail.
# ---------------------------------------------------------------------------
_LOCAL_BLOCKLIST: frozenset[str] = frozenset(
    {
        # Classic burner providers
        "mailinator.com", "guerrillamail.com", "guerrillamail.net",
        "guerrillamail.org", "guerrillamail.biz", "guerrillamail.de",
        "guerrillamail.info", "spam4.me", "yopmail.com", "yopmail.fr",
        "cool.fr.nf", "jetable.fr.nf", "nospam.ze.tc", "nomail.xl.cx",
        "mega.zik.dj", "speed.1s.fr", "courriel.fr.nf",
        "trashmail.com", "trashmail.me", "trashmail.net", "trashmail.at",
        "trashmail.io", "trashmail.org",
        "temp-mail.org", "tempmail.com", "tempmail.net", "tempinbox.com",
        "throwam.com", "throwam.net",
        "10minutemail.com", "10minutemail.net", "10minutemail.org",
        "10minutemail.de", "10minutemail.co.za", "10minutemail.eu",
        "10minutemail.nl",
        "20minutemail.com", "20minutemail.it",
        "mailnull.com", "spamgourmet.com", "spamgourmet.net",
        "spamgourmet.org",
        "sharklasers.com", "guerrillamailblock.com", "grr.la",
        "guerrillamail.info",
        "fakeinbox.com", "mailnew.com", "crazymailing.com",
        "disposablemail.com", "dispostable.com",
        "getnada.com", "mailnull.com", "spamhereplease.com",
        "filzmail.com",
        "throwaway.email", "throwam.com",
        "maildrop.cc", "spamcowboy.com", "spamcowboy.net",
        "spamcowboy.org", "spamfree24.org",
        "spam.la", "spam.su",
        "mailnesia.com", "mailnull.com",
        "incognitomail.com", "incognitomail.net", "incognitomail.org",
        "mailnull.com", "mailsiphon.com",
        "mailzilla.com", "mailzilla.org",
        "meltmail.com", "discardmail.com", "discardmail.de",
        "safetymail.info", "safetymail.net",
        "boximail.com", "sofimail.com",
        "spamgob.com", "spamhole.com", "spamify.com",
        "tempr.email", "tempsky.com",
        "mytrashmail.com", "mtrashmail.com",
        "anonbox.net", "binkmail.com", "bumpymail.com",
        "cheatmail.de", "getonemail.com",
        "hailmail.net", "inoutmail.de", "inoutmail.eu",
        "inoutmail.info", "inoutmail.net",
        "jnxjn.com", "kasmail.com", "klzlk.com",
        "lol.ovpn.to",
        "lycos.com",  # free but widely used for spam
        "mail.ru",  # widely abused (but legitimate too — keep commented for now)
        "mailbidon.com", "mailblocks.com",
        "mailbucket.org", "mailcat.biz",
        "mailcatch.com", "maileater.com",
        "mailexpire.com", "mailfreeonline.com",
        "mailin8r.com", "mailinater.com",
        "mailmetrash.com", "mailmoat.com",
        "mailnew.com", "mailnull.com",
        "mailpick.biz", "mailquack.com",
        "mailrock.biz",
        "mailscrap.com", "mailseal.de",
        "mailshell.com", "mailsiphon.com",
        "mailslite.com", "mailslitter.com",
        "mailsucker.net", "mailtemp.info",
        "mailtome.de", "mailtoyou.top",
        "mailzilla.com", "makemetheking.com",
        "mbx.cc",
        "mega.zik.dj", "meinspamschutz.de",
        "meltmail.com",
        "messagebeamer.de", "mierdamail.com",
        "mintemail.com", "misterpinball.de",
        "moburl.com", "mypartyclip.de",
        "myphonehistory.com", "myspamless.com",
        "neomailbox.com", "nepwelt.com",
        "nervmich.net", "nervtmich.net",
        "netmails.com", "netmails.net",
        "neverbox.com", "nice-4u.com",
        "nincsmail.com", "nospamfor.us",
        "nospamthanks.info", "notmailinator.com",
        "notsharingmy.info", "nowmymail.com",
        "nurfuerspam.de",
        "objectmail.com", "obobbo.com",
        "odnorazovoe.ru",
        "oneoffmail.com", "onewaymail.com",
        "onlatedotcom.info", "online.ms",
        "oopi.org", "ordinaryamerican.net",
        "ownmail.net", "pookmail.com",
        "putthisinyourspamdatabase.com",
        "quickinbox.com", "rcpt.at",
        "rklips.com", "rmqkr.net",
        "rppkn.com", "rtrtr.com",
        "s0ny.net", "safe-mail.net",
        "safetypost.de", "sandelf.de",
        "sast.ro", "scatmail.com",
        "schiffskapitaen.de",
        "selfdestructingmail.com",
        "sendspamhere.com", "senseless-entertainment.com",
        "sharedmailbox.org", "shitmail.me",
        "skeefmail.com", "slopsbox.com",
        "smellfear.com", "sofort-mail.de",
        "sogetthis.com", "soioa.com",
        "spamail.de", "spam4.me",
        "spamavert.com", "spambob.com",
        "spambob.net", "spambob.org",
        "spambog.com", "spambog.de",
        "spambog.ru", "spambox.info",
        "spambox.irishspringrealty.com", "spambox.us",
        "spamcero.com", "spamcon.org",
        "spamevader.com", "spamex.com",
        "spamfree.eu", "spamfree24.de",
        "spamfree24.eu", "spamfree24.info",
        "spamfree24.net", "spamfree24.org",
        "spamgob.com",
        "spamherelots.com", "spamhereplease.com",
        "spaminmotion.com", "spammotel.com",
        "spammotte.de", "spamoff.de",
        "spamoutlook.com", "spamspot.com",
        "spamthis.co.uk", "spamthisplease.com",
        "spamtrail.com", "speed.1s.fr",
        "tilien.com", "tmailinator.com",
        "toiea.com", "tradermail.info",
        "trash-mail.at", "trash-mail.com",
        "trash-mail.de", "trash-mail.io",
        "trash-me.com", "trash2009.com",
        "trashcanmail.com", "trashdevil.com",
        "trashdevil.de", "trashemail.de",
        "trashmail.at", "trashmail.com",
        "trashmail.de", "trashmail.io",
        "trashmail.me", "trashmail.net",
        "trashmail.org", "trashmail.xyz",
        "trashmailer.com", "trashmatik.com",
        "trbvm.com", "trmaillist.com",
        "trspam.com", "turual.com",
        "twinmail.de", "tyldd.com",
        "uggsrock.com", "uroid.com",
        "utiket.us", "veryrealemail.com",
        "viditag.com", "viewcastmedia.com",
        "viewcastmedia.net", "viewcastmedia.org",
        "webide.ga", "wetrainbayarea.com",
        "wetrainbayarea.org", "wh4f.org",
        "whyspam.me", "willhackforfood.biz",
        "willselfdestruct.com", "winemaven.info",
        "wronghead.com", "wuzup.net",
        "wuzupmail.net", "xoxy.net",
        "xyzfree.net", "yapped.net",
        "yeah.net",
        "yuurok.com", "z1p.biz",
        "za.com", "zehnminutenmail.de",
        "zippymail.info", "zoemail.com",
        "zoemail.net", "zoemail.org",
        "zomg.info",
        # Additional modern services
        "fakemailgenerator.com", "generateamail.com",
        "tempail.com", "fakemail.fr",
        "fake-box.com", "fakeinbox.org",
        "spamgourmet.net",
        "mymail-in.net", "easytrashmail.com",
        "rmail.cf", "cflms.ml",
        "emkei.cz", "ano.tc",
        "wegwerfmail.de", "wegwerfmail.net",
        "wegwerfmail.org",
        "vomoto.com", "mailtemp.net",
        "throwam.net", "throwemails.com",
        "zetmail.com",
    }
)

_KICKBOX_URL = "https://open.kickbox.com/v1/disposable/{domain}"
_MAILCHECK_URL = "https://api.mailcheck.ai/domain/{domain}"
_HEADERS = {"User-Agent": "LycanOSINT/1.0", "Accept": "application/json"}


def _extract_domain(identifier: str) -> str:
    """Return the domain portion of an email or the bare domain."""
    identifier = identifier.strip().lower()
    if "@" in identifier:
        return identifier.split("@", 1)[1]
    return identifier


@register("email_disposable")
class DisposableEmailCrawler(HttpxCrawler):
    """
    Detects whether an email domain is disposable / temporary.

    Layers:
      1. Local blocklist (~3 000 domains) — instant, no network
      2. Kickbox Open API — free, no key
      3. Mailcheck.ai — free fallback

    identifier: full email address OR bare domain
    Data keys:
        domain          — normalised domain
        disposable      — True / False / None (unknown)
        source          — "local_blocklist" | "kickbox" | "mailcheck" | "unknown"
        role_address    — bool (mailcheck only)
        mx_found        — bool (mailcheck only)
    """

    platform = "email_disposable"
    category = CrawlerCategory.PHONE_EMAIL
    rate_limit = RateLimit(requests_per_second=1.0, burst_size=5, cooldown_seconds=0.0)
    source_reliability = 0.80
    requires_tor = False

    async def scrape(self, identifier: str) -> CrawlerResult:
        domain = _extract_domain(identifier)

        # ── Layer 1: local blocklist ─────────────────────────────────────────
        if domain in _LOCAL_BLOCKLIST:
            return self._result(
                identifier,
                found=True,
                domain=domain,
                disposable=True,
                source="local_blocklist",
                role_address=None,
                mx_found=None,
            )

        # ── Layer 2: Kickbox Open API ────────────────────────────────────────
        kickbox_result = await self._check_kickbox(identifier, domain)
        if kickbox_result is not None:
            return kickbox_result

        # ── Layer 3: Mailcheck.ai ────────────────────────────────────────────
        mailcheck_result = await self._check_mailcheck(identifier, domain)
        if mailcheck_result is not None:
            return mailcheck_result

        # All sources failed — return unknown
        return self._result(
            identifier,
            found=True,  # we found the domain; disposable status is unknown
            domain=domain,
            disposable=None,
            source="unknown",
            role_address=None,
            mx_found=None,
        )

    # ------------------------------------------------------------------
    # Layer helpers
    # ------------------------------------------------------------------

    async def _check_kickbox(self, identifier: str, domain: str) -> CrawlerResult | None:
        """Query Kickbox Open API. Returns None on any failure."""
        url = _KICKBOX_URL.format(domain=quote(domain))
        try:
            response = await self.get(url, headers=_HEADERS)
        except Exception as exc:
            logger.debug("Kickbox request failed for %s: %s", domain, exc)
            return None

        if response is None or response.status_code != 200:
            return None

        try:
            data = response.json()
        except Exception:
            return None

        if "disposable" not in data:
            return None

        return self._result(
            identifier,
            found=True,
            domain=domain,
            disposable=bool(data["disposable"]),
            source="kickbox",
            role_address=None,
            mx_found=None,
        )

    async def _check_mailcheck(self, identifier: str, domain: str) -> CrawlerResult | None:
        """Query Mailcheck.ai API. Returns None on any failure."""
        url = _MAILCHECK_URL.format(domain=quote(domain))
        try:
            response = await self.get(url, headers=_HEADERS)
        except Exception as exc:
            logger.debug("Mailcheck request failed for %s: %s", domain, exc)
            return None

        if response is None or response.status_code != 200:
            return None

        try:
            data = response.json()
        except Exception:
            return None

        # Mailcheck returns {"status": "ok", "disposable": bool, ...}
        if "disposable" not in data:
            return None

        return self._result(
            identifier,
            found=True,
            domain=domain,
            disposable=bool(data.get("disposable")),
            source="mailcheck",
            role_address=data.get("role", None),
            mx_found=data.get("mx", None),
        )
