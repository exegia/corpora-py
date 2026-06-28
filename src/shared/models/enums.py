import enum

# ── Enumerations ──────────────────────────────────────────────────────────────

class BookCategory(str, enum.Enum):
	BIBLE = "bible"
	QURAN = "quran"
	TANAKH = "tanakh"
	COMMENTARY = "commentary"
	LEXICON = "lexicon"
	DICTIONARY = "dictionary"
	DEVOTIONAL = "devotional"
	THEOLOGY = "theology"
	HISTORY = "history"
	PHILOSOPHY = "philosophy"
	FICTION = "fiction"
	OTHER = "other"


class BookSourceType(str, enum.Enum):
	EPUB = "epub"
	PDF = "pdf"
	URL = "url"
	MANUAL = "manual"


class SectionType(str, enum.Enum):
	PART = "part"
	CHAPTER = "chapter"
	SECTION = "section"
	ARTICLE = "article"
	ENTRY = "entry"
	APPENDIX = "appendix"
	INTRODUCTION = "introduction"
	PREFACE = "preface"
	FOREWORD = "foreword"
	INDEX = "index"
	GLOSSARY = "glossary"
	OTHER = "other"
