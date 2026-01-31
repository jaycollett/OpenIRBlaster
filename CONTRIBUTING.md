# Contributing to OpenIRBlaster

Thank you for your interest in contributing to OpenIRBlaster! This project welcomes contributions of all kinds - code, documentation, hardware improvements, bug reports, and feature suggestions.

## Ways to Contribute

### Report Bugs
- Check existing [issues](https://github.com/jaycollett/OpenIRBlaster/issues) first
- Include Home Assistant version, ESPHome version, and integration version
- Provide relevant log output (filter for `openirblaster`)
- Describe expected vs actual behavior

### Suggest Features
- Open an issue describing the feature and use case
- Explain how it fits with the project's goals

### Improve Documentation
- Fix typos, clarify instructions, add examples
- Update the [Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki)

### Submit Code
- Bug fixes, new features, refactoring
- See development setup below

### Hardware Contributions
- PCB improvements, enclosure designs, component alternatives
- Add files to the `hardware/` directory

## Development Setup

### Prerequisites
- Python 3.12+
- Home Assistant development environment (or a test HA instance)
- ESPHome device with OpenIRBlaster firmware (for integration testing)

### Clone and Install
```bash
git clone https://github.com/jaycollett/OpenIRBlaster.git
cd OpenIRBlaster
python3 -m venv venv
source venv/bin/activate
pip install -r requirements_dev.txt
```

### Run Tests
```bash
pytest
pytest --cov=custom_components.openirblaster --cov-report=term-missing
```

### Local Testing with Home Assistant
See [TESTING.md](TESTING.md) for detailed instructions on testing with a real Home Assistant instance.

## Pull Request Process

1. **Fork the repository** and create a feature branch from `master`
2. **Make your changes** with clear, focused commits
3. **Run tests** and ensure they pass
4. **Update documentation** if needed
5. **Submit a PR** with a clear description of changes

### PR Guidelines
- Keep PRs focused - one feature or fix per PR
- Include tests for new functionality
- Update relevant documentation
- Reference any related issues

## Code Style

### Python (Home Assistant Integration)
- Follow [Home Assistant development guidelines](https://developers.home-assistant.io/docs/development_index)
- Use type hints
- Keep functions focused and readable
- Add docstrings for public functions

### ESPHome (Firmware)
- Follow ESPHome YAML conventions
- Comment non-obvious configurations
- Test on actual hardware before submitting

### Commit Messages
- Use clear, descriptive commit messages
- Start with a verb (Add, Fix, Update, Remove)
- Keep the first line under 72 characters
- Reference issues when applicable (e.g., "Fix #123")

Examples:
```
Add support for NEC protocol decoding
Fix learning timeout not resetting after cancel
Update README with HACS installation steps
```

## Testing Requirements

### For Integration Changes
- Unit tests for new functionality
- Test learning workflow manually with real hardware
- Verify entities are created/removed correctly
- Check that storage persists across restarts

### For Firmware Changes
- Test on ESP8266 hardware
- Verify IR receive and transmit functionality
- Ensure compatibility with the Home Assistant integration

## Project Structure

```
OpenIRBlaster/
├── custom_components/openirblaster/   # Home Assistant integration
│   ├── __init__.py                    # Integration setup
│   ├── button.py                      # Button entities
│   ├── config_flow.py                 # Setup and options flows
│   ├── learning.py                    # IR learning state machine
│   ├── storage.py                     # Code storage management
│   └── ...
├── hardware/                          # Hardware design files
│   ├── firmware/                      # ESPHome configurations
│   └── ...
├── tests/                             # pytest test suite
└── ...
```

## Questions?

- Open an issue for questions about contributing
- Check the [Wiki](https://github.com/jaycollett/OpenIRBlaster/wiki) for project documentation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
