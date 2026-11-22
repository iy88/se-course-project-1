pipeline {
    agent any

    tools {
        jdk 'jdk-27'
        nodejs 'node-latest'
    }

    environment {
        PROJECT1_V2_DEPLOY_HOST = '192.168.3.221'
        PROJECT1_V2_DEPLOY_USER = 'deploy'
    }

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    stages {
        stage('Checkout') {
            steps {
                deleteDir()
                script {
                    checkout scm
                    env.RELEASE_REVISION = sh(script: '''
                        set -eu
                        revision=$(git rev-parse HEAD)
                        test "$revision" = "$(git rev-parse refs/remotes/origin/main)"
                        echo "$revision"
                    ''', returnStdout: true).trim()
                }
            }
        }

        stage('Validate deployment assets') {
            steps {
                sh '''
                    set -eu
                    config=scripts/deploy/config/.env.deploy.example
                    for output in upstream units; do
                        python3 scripts/deploy/render-runtime.py "$config" "$output" > /dev/null
                    done
                    python3 scripts/deploy/render-runtime.py "$config" sudoers --deploy-user deploy > /dev/null
                    for script in scripts/deploy/*.sh; do
                        bash -n "$script"
                    done
                '''
            }
        }

        stage('Build and package') {
            steps {
                sh 'bash scripts/deploy/build-release.sh release-artifacts "$BUILD_NUMBER"'
                archiveArtifacts(
                    artifacts: 'release-artifacts/*/*.tar.gz,release-artifacts/*/SHA256SUMS',
                    fingerprint: true,
                    allowEmptyArchive: false
                )
            }
        }

        stage('Deploy on source server') {
            steps {
                sshagent(credentials: ['project1-v2-deploy']) {
                    sh 'bash scripts/deploy/upload-release.sh "release-artifacts/${RELEASE_REVISION}-${BUILD_NUMBER}"'
                }
            }
        }
    }
}
