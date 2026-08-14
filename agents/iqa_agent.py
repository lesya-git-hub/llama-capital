from models.research_report import ResearchReport


class IQAAgent:
    def review(self, report: ResearchReport) -> tuple[bool, list[str]]:
        issues = []

        if report.confidence >= 80 and not report.strengths:
            issues.append(
                "High-confidence report must include supporting strengths."
            )

        if report.recommendation == "BUY" and report.confidence < 70:
            issues.append(
                "BUY recommendation requires confidence of at least 70."
            )

        if not report.risks:
            issues.append(
                "Research report must include at least one risk."
            )

        if report.summary.strip() == "":
            issues.append(
                "Research summary is missing."
            )

        passed = len(issues) == 0

        return passed, issues