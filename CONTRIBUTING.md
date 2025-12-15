# 📋 Contributing to OCRPDF-TO-PPT

Thank you for your interest in contributing to OCRPDF-TO-PPT! This document provides guidelines and instructions for contributing.

## 🌟 Ways to Contribute

- 🐛 Report bugs
- 💡 Suggest new features
- 📝 Improve documentation
- 🔧 Submit code changes
- 🌍 Translate documentation
- ⭐ Star the project

## 🚀 Getting Started

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/OCRPDF-TO-PPT.git
cd OCRPDF-TO-PPT
```

### 2. Set Up Development Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development tools
pip install black isort mypy pylint pytest pytest-cov
```

### 3. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b bugfix/issue-number
```

## 📝 Code Standards

### Code Style

We use the following tools to maintain code quality:

```bash
# Format code
black ppt_editor_modular/
isort ppt_editor_modular/

# Type checking
mypy ppt_editor_modular/ --ignore-missing-imports

# Linting
pylint ppt_editor_modular/
```

### Commit Messages

Follow conventional commit format:

```
type(scope): subject

body (optional)

footer (optional)
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**

```bash
git commit -m "feat(ocr): add batch processing support"
git commit -m "fix(cache): resolve memory leak in ImageCache"
git commit -m "docs: update installation instructions"
```

### Code Guidelines

1. **Type Hints**: Use type hints for all function parameters and returns
2. **Docstrings**: Add docstrings for all public functions and classes
3. **Error Handling**: Use specific exception types, avoid bare `except`
4. **Logging**: Use the logging system instead of `print()`
5. **Resource Management**: Use context managers for resource cleanup

**Example:**

```python
from typing import Optional
import logging

logger = logging.getLogger(__name__)

def process_image(image_path: str, size: tuple[int, int]) -> Optional[Image.Image]:
    """
    Process an image file.

    Args:
        image_path: Path to the image file
        size: Target size as (width, height)

    Returns:
        Processed image or None if processing fails

    Raises:
        FileNotFoundError: If image file doesn't exist
    """
    try:
        with Image.open(image_path) as img:
            return img.resize(size)
    except FileNotFoundError:
        logger.error(f"Image not found: {image_path}")
        raise
    except Exception as e:
        logger.error(f"Failed to process image: {e}")
        return None
```

## 🧪 Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ppt_editor_modular tests/

# Run specific test file
pytest tests/test_textbox.py
```

### Writing Tests

Add tests for all new features:

```python
# tests/test_feature.py
import pytest
from ppt_editor_modular.feature import MyFeature

def test_feature_creation():
    feature = MyFeature()
    assert feature is not None

def test_feature_processing():
    feature = MyFeature()
    result = feature.process("input")
    assert result == "expected_output"

def test_feature_error_handling():
    feature = MyFeature()
    with pytest.raises(ValueError):
        feature.process(None)
```

## 📚 Documentation

### Code Documentation

- Add docstrings to all public APIs
- Include type hints
- Provide usage examples in docstrings

### User Documentation

Update relevant documentation files:
- `README.md` - Main documentation
- `docs/QUICKSTART.md` - Quick start guide
- `docs/API.md` - API documentation
- `CHANGELOG.md` - Record changes

## 🔄 Pull Request Process

### 1. Before Submitting

- [ ] Code follows project style guidelines
- [ ] All tests pass
- [ ] Added tests for new features
- [ ] Documentation is updated
- [ ] Commit messages follow conventions
- [ ] No merge conflicts

### 2. Submit PR

1. Push your branch to your fork
2. Go to the original repository
3. Click "New Pull Request"
4. Fill in the PR template
5. Link related issues

### 3. PR Template

```markdown
## Description
Brief description of the changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
Describe the tests you ran

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added where needed
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] Tests added
- [ ] All tests pass
```

### 4. Review Process

- Maintainers will review your PR
- Address feedback and make requested changes
- Once approved, your PR will be merged

## 🐛 Reporting Bugs

### Before Reporting

1. Check [existing issues](https://github.com/Tansuo2021/OCRPDF-TO-PPT/issues)
2. Try the latest version
3. Check the [FAQ](docs/FAQ.md)

### Bug Report Template

```markdown
**Describe the bug**
A clear description of the bug

**To Reproduce**
Steps to reproduce:
1. Go to '...'
2. Click on '....'
3. See error

**Expected behavior**
What you expected to happen

**Screenshots**
If applicable, add screenshots

**Environment:**
 - OS: [e.g. Windows 10]
 - Python Version: [e.g. 3.8.5]
 - Project Version: [e.g. v2.0.0]

**Additional context**
Any other relevant information
```

## 💡 Suggesting Features

### Feature Request Template

```markdown
**Is your feature request related to a problem?**
A clear description of the problem

**Describe the solution you'd like**
What you want to happen

**Describe alternatives you've considered**
Other solutions you've thought about

**Additional context**
Any other relevant information
```

## 📖 Resources

- [Project Documentation](docs/)
- [API Reference](docs/API.md)
- [Development Guide](docs/REFACTORING_GUIDE.md)
- [Issue Tracker](https://github.com/Tansuo2021/OCRPDF-TO-PPT/issues)

## 🤝 Community

- Be respectful and inclusive
- Help others learn and grow
- Give constructive feedback
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md)

## 📞 Questions?

If you have questions about contributing:
- Open a [Discussion](https://github.com/Tansuo2021/OCRPDF-TO-PPT/discussions)
- Ask in an [Issue](https://github.com/Tansuo2021/OCRPDF-TO-PPT/issues)

---

Thank you for contributing to OCRPDF-TO-PPT! 🎉
