import argparse
from scheduler import run_simulation

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Jira Activity Simulator')
    parser.add_argument('--events', type=int, default=3, help="Nombre d'événements à simuler")
    parser.add_argument('--dry-run', action='store_true', help='Force le mode dry-run')
    args = parser.parse_args()
    run_simulation(n_events=args.events)
