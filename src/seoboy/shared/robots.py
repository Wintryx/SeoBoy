"""Parser und Auswertung für robots.txt nach RFC 9309 (Kernregeln)."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from seoboy.shared.agents import GOOGLEBOT, SEOBOY


@dataclass(frozen=True)
class RobotsRule:
    allow: bool
    pattern: str
    regex: re.Pattern[str]

    @property
    def text(self) -> str:
        return f"{'Allow' if self.allow else 'Disallow'}: {self.pattern}"


@dataclass
class RobotsGroup:
    agents: list[str] = field(default_factory=list)
    rules: list[RobotsRule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    rule: RobotsRule | None
    agent_token: str | None
    matched: bool

    @property
    def description(self) -> str:
        if self.rule is None:
            return "keine passende Regel"
        return f"{self.rule.text} (Gruppe {self.agent_token or '*'} )"


def _compile_rule(pattern: str) -> re.Pattern[str]:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    pieces: list[str] = []
    index = 0
    while index < len(body):
        character = body[index]
        if character == "*":
            pieces.append(".*")
        else:
            pieces.append(re.escape(character))
        index += 1
    if anchored:
        pieces.append("$")
    return re.compile("".join(pieces))


class RobotsFile:
    def __init__(
        self,
        groups: list[RobotsGroup] | None = None,
        sitemaps: list[str] | None = None,
        raw: str = "",
    ) -> None:
        self.groups = groups or []
        self.sitemaps = sitemaps or []
        self.raw = raw

    @classmethod
    def parse(cls, text: str) -> "RobotsFile":
        groups: list[RobotsGroup] = []
        sitemaps: list[str] = []
        current: RobotsGroup | None = None
        last_was_agent = False
        for raw_line in text.lstrip("\ufeff").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            key, separator, value = line.partition(":")
            if not separator:
                continue
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if current is None or not last_was_agent and current.rules:
                    current = RobotsGroup()
                    groups.append(current)
                current.agents.append(value.casefold())
                last_was_agent = True
            elif key in {"allow", "disallow"}:
                if current is None:
                    continue
                last_was_agent = False
                if key == "disallow" and value == "":
                    continue
                current.rules.append(
                    RobotsRule(allow=key == "allow", pattern=value, regex=_compile_rule(value))
                )
            elif key == "sitemap":
                if value:
                    sitemaps.append(value)
            elif key == "crawl-delay":
                if current is not None:
                    try:
                        current.crawl_delay = float(value.replace(",", "."))
                    except ValueError:
                        pass
        return cls(groups=groups, sitemaps=sitemaps, raw=text)

    def _matching_groups(self, agent: str) -> tuple[list[RobotsGroup], str | None]:
        token = agent.strip().casefold()
        best_length = -1
        best_token: str | None = None
        for group in self.groups:
            for group_agent in group.agents:
                if group_agent == "*":
                    length = 0
                elif token.startswith(group_agent):
                    length = len(group_agent)
                else:
                    continue
                if length > best_length:
                    best_length = length
                    best_token = group_agent
        if best_token is None:
            return [], None
        matching = [group for group in self.groups if best_token in {a.casefold() for a in group.agents}]
        return matching, best_token

    def evaluate(self, path: str, agent: str = GOOGLEBOT) -> RobotsDecision:
        groups, token = self._matching_groups(agent)
        if not groups:
            return RobotsDecision(True, None, token, False)
        winner: RobotsRule | None = None
        winner_length = -1
        for group in groups:
            for rule in group.rules:
                if rule.regex.match(path):
                    length = len(rule.pattern.rstrip("$"))
                    if length > winner_length or (
                        length == winner_length and rule.allow and winner is not None
                    ):
                        winner = rule
                        winner_length = length
        if winner is None:
            return RobotsDecision(True, None, token, True)
        return RobotsDecision(winner.allow, winner, token, True)

    def is_allowed(self, path: str, agent: str = GOOGLEBOT) -> bool:
        return self.evaluate(path, agent).allowed
