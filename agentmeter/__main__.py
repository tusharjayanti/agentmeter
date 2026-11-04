from .cli import main

if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
