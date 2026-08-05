from models.research_report import ResearchReport


class QAAgent:
    def review(self, report: ResearchReport) -> tuple[bool, list[str]]:
        issues = []

        if not report.summary.strip():
            issues.append("Missing summary.")

        if not report.strengths:
            issues.append("Missing strengths.")

        if not report.risks:
            issues.append("Missing risks.")

        if report.confidence < 0 or report.confidence > 100:
            issues.append("Confidence must be between 0 and 100.")

        if report.recommendation not in {"REJECT", "MONITOR", "RESEARCH", "BUY"}:
            issues.append("Invalid recommendation.")

        return len(issues) == 0, issues