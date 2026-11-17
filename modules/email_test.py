from modules.email_service import EmailService


def main():
    service = EmailService()
    print("Connecting to IMAP...")
    replies = service.fetch_unread_replies()

    if replies:
        for r in replies:
            print("\n--- NEW EMAIL RECEIVED ---")
            print(f"Subject: {r['subject']}")
            print(f"Cleaned Body:\n{r['body']}")
    else:
        print("No unread emails found from your address yet.")


if __name__ == "__main__":
    main()
