def valid_filters(kind, subject, before):
    return (
        kind in {"all", "gained", "lost"}
        and subject in {"followers", "subscriptions"}
        and before >= 0
    )
