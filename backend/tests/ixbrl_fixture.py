"""Builds small inline XBRL documents for tests: cover page facts, contexts, units, tagged values and note text blocks."""

from __future__ import annotations

NAMESPACES = {
    "ix": "http://www.xbrl.org/2013/inlineXBRL",
    "ixt": "http://www.xbrl.org/inlineXBRL/transformation/2020-02-12",
    "ixt-sec": "http://www.sec.gov/inlineXBRL/transformation/2015-08-31",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "xbrldi": "http://xbrl.org/2006/xbrldi",
    "iso4217": "http://www.xbrl.org/2003/iso4217",
    "us-gaap": "http://fasb.org/us-gaap/2026",
    "ifrs-full": "https://xbrl.ifrs.org/taxonomy/2025-03-27/ifrs-full",
    "dei": "http://xbrl.sec.gov/dei/2026",
    "acme": "http://acme.example/20260726",
}

UNITS = {
    "usd": "<xbrli:measure>iso4217:USD</xbrli:measure>",
    "eur": "<xbrli:measure>iso4217:EUR</xbrli:measure>",
    "shares": "<xbrli:measure>xbrli:shares</xbrli:measure>",
    "pure": "<xbrli:measure>xbrli:pure</xbrli:measure>",
    "usdPerShare": "<xbrli:divide><xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unitNumerator>"
                   "<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure></xbrli:unitDenominator></xbrli:divide>",
}


def context(cid: str, start: str | None = None, end: str | None = None, instant: str | None = None, dims=()) -> str:
    period = f"<xbrli:instant>{instant}</xbrli:instant>" if instant else f"<xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate>"
    members = "".join(f'<xbrldi:explicitMember dimension="{axis}">{member}</xbrldi:explicitMember>' for axis, member in dims)
    segment = f"<xbrli:segment>{members}</xbrli:segment>" if members else ""
    return (f'<xbrli:context id="{cid}"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001'
            f"</xbrli:identifier>{segment}</xbrli:entity><xbrli:period>{period}</xbrli:period></xbrli:context>")


def value(name: str, ctx: str, text: str, unit: str = "usd", scale: int = 6, decimals: int | str = -6,
          fmt: str | None = "ixt:num-dot-decimal", sign: str | None = None, fid: str | None = None) -> str:
    attrs = f'name="{name}" contextRef="{ctx}" unitRef="{unit}" scale="{scale}" decimals="{decimals}"'
    attrs += f' format="{fmt}"' if fmt else ""
    attrs += f' sign="{sign}"' if sign else ""
    attrs += f' id="{fid}"' if fid else ""
    return f"<ix:nonFraction {attrs}>{text}</ix:nonFraction>"


def row(label: str, *cells: str) -> str:
    return "<table><tr><td>" + label + "</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr></table>"


def text_block(name: str, ctx: str, inner: str, bid: str, continued_at: str | None = None) -> str:
    more = f' continuedAt="{continued_at}"' if continued_at else ""
    return f'<ix:nonNumeric name="{name}" contextRef="{ctx}" escape="true" id="{bid}"{more}>{inner}</ix:nonNumeric>'


def continuation(cid: str, inner: str, continued_at: str | None = None) -> str:
    more = f' continuedAt="{continued_at}"' if continued_at else ""
    return f'<ix:continuation id="{cid}"{more}>{inner}</ix:continuation>'


def cover(ctx: str, doc_type: str, period_end: str, fiscal_year: int, fiscal_period: str, amendment: bool = False,
          fiscal_year_end: str = "--12-31") -> str:
    return (
        f'<ix:nonNumeric name="dei:DocumentType" contextRef="{ctx}">{doc_type}</ix:nonNumeric>'
        f'<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="{ctx}">{period_end}</ix:nonNumeric>'
        f'<ix:nonNumeric name="dei:DocumentFiscalYearFocus" contextRef="{ctx}">{fiscal_year}</ix:nonNumeric>'
        f'<ix:nonNumeric name="dei:DocumentFiscalPeriodFocus" contextRef="{ctx}">{fiscal_period}</ix:nonNumeric>'
        f'<ix:nonNumeric name="dei:AmendmentFlag" contextRef="{ctx}">{"true" if amendment else "false"}</ix:nonNumeric>'
        f'<ix:nonNumeric name="dei:CurrentFiscalYearEndDate" contextRef="{ctx}">{fiscal_year_end}</ix:nonNumeric>'
    )


def document(body: str, contexts: list[str] = (), units: dict[str, str] = UNITS, prefixes: dict[str, str] = NAMESPACES,
             header: bool = True) -> str:
    declarations = " ".join(f'xmlns:{p}="{uri}"' for p, uri in prefixes.items())
    resources = "".join(contexts) + "".join(f'<xbrli:unit id="{uid}">{m}</xbrli:unit>' for uid, m in units.items())
    head = f'<div style="display:none"><ix:header><ix:resources>{resources}</ix:resources></ix:header></div>' if header else ""
    return (f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml" {declarations}>'
            f"<head><title>filing</title></head><body>{head}{body}</body></html>")
