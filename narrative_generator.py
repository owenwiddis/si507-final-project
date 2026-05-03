"""
narrative_generator.py
Wraps the Anthropic API to generate natural language cascade stories.
"""

import os
import anthropic
from disaster_event import DisasterEvent


class NarrativeGenerator:
    """
    Generates natural language explanations of disaster cascade paths
    using Claude (claude-haiku-4-5 for cost efficiency).

    Args:
        api_key (str): Anthropic API key. Reads ANTHROPIC_API_KEY env var if None.
    """

    def __init__(self, api_key: str = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var "
                "or pass api_key= to NarrativeGenerator()."
            )
        self.client = anthropic.Anthropic(api_key=key)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate_cascade_story(
        self,
        cascade_path: list[DisasterEvent],
        max_tokens: int = 400,
    ) -> str:
        """
        Generate a narrative explanation for a cascade sequence.

        Args:
            cascade_path: Ordered list of DisasterEvent objects (trigger → final result).
            max_tokens:   Max tokens in Claude's response.

        Returns:
            Natural language explanation of the cascade mechanism.
        """
        if not cascade_path:
            return "No cascade path provided."

        prompt = self._build_prompt(cascade_path)

        message = self.client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = max_tokens,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    def generate_event_summary(self, event: DisasterEvent) -> str:
        """Generate a one-paragraph plain-English summary of a single event."""
        prompt = (
            f"Briefly summarize this California disaster event in 2-3 sentences "
            f"for a general audience. Focus on what happened, where, and why it matters "
            f"for understanding climate cascades.\n\n"
            f"Event type: {event.event_type}\n"
            f"County: {event.county}\n"
            f"Date: {event.start_date.date()} to {event.end_date.date()}\n"
            f"Severity score: {event.severity_score}/100\n"
            f"Deaths: {event.deaths_direct + event.deaths_indirect}\n"
            f"Property damage: ${event.damage_property:,.0f}\n"
            f"NOAA narrative: {event.narrative[:500] if event.narrative else 'Not available'}\n"
        )
        message = self.client.messages.create(
            model      = "claude-haiku-4-5-20251001",
            max_tokens = 150,
            messages   = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_prompt(self, cascade_path: list[DisasterEvent]) -> str:
        """Build the prompt for a cascade story."""
        chain_desc = []
        for i, event in enumerate(cascade_path):
            chain_desc.append(
                f"Step {i+1}: {event.event_type} in {event.county} County "
                f"({event.start_date.strftime('%B %Y')}, severity {event.severity_score}/100)"
            )
        chain_str = "\n".join(chain_desc)

        return (
            "You are a climate scientist explaining disaster cascade mechanisms "
            "to a non-technical audience. Given the following sequence of California "
            "climate disasters, explain in 3-5 sentences how each event likely "
            "contributed to triggering the next one. Focus on the physical mechanisms "
            "(soil moisture, vegetation, hillside stability, etc.). Be specific and vivid.\n\n"
            f"Cascade sequence:\n{chain_str}\n\n"
            "Explain the cascade:"
        )
